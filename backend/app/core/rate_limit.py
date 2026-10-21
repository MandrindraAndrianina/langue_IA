"""Limitation de débit (seau à jetons) contre le brute force des connexions.

Bucket4j n'existe pas côté Python : on implémente le même algorithme (token bucket) sans
dépendance. Le compteur est tenu en mémoire, par adresse IP et par processus. Cela suffit à
un déploiement mono-instance ; derrière plusieurs workers il faudrait un stockage partagé
(Redis) pour que la limite soit globale.

Le filtre est branché en dépendance FastAPI sur la route de connexion : il consomme un jeton
à chaque tentative et renvoie 429 (avec `Retry-After`) quand le seau est vide.
"""

import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

# Au-delà, les seaux redevenus pleins (donc sans effet) sont supprimés pour borner la mémoire.
SEUIL_PURGE = 1024


@dataclass
class _Seau:
    jetons: float
    dernier: float


class LimiteurTentatives:
    """`capacite` tentatives en rafale, reconstituées au rythme de `capacite` / `fenetre` par seconde."""

    def __init__(self, capacite: int, fenetre: float) -> None:
        self.capacite = capacite
        self.fenetre = fenetre
        self._seaux: dict[str, _Seau] = {}
        self._verrou = threading.Lock()

    def _taux(self) -> float:
        if self.fenetre <= 0:
            return float("inf")
        return self.capacite / self.fenetre

    def consommer(self, cle: str, maintenant: float | None = None) -> float:
        """Consomme un jeton pour `cle`.

        Renvoie 0 si la tentative est autorisée, sinon le nombre de secondes avant qu'un jeton
        soit reconstitué.
        """
        instant = time.monotonic() if maintenant is None else maintenant
        with self._verrou:
            if len(self._seaux) > SEUIL_PURGE:
                self._purger()
            seau = self._seaux.get(cle)
            if seau is None:
                seau = _Seau(jetons=float(self.capacite), dernier=instant)
                self._seaux[cle] = seau
            else:
                seau.jetons = min(self.capacite, seau.jetons + (instant - seau.dernier) * self._taux())
                seau.dernier = instant
            if seau.jetons >= 1:
                seau.jetons -= 1
                return 0.0
            return (1 - seau.jetons) / self._taux()

    def reinitialiser(self) -> None:
        with self._verrou:
            self._seaux.clear()

    def _purger(self) -> None:
        """Retire les seaux pleins : ils équivalent à une absence d'historique."""
        for cle in [cle for cle, seau in self._seaux.items() if seau.jetons >= self.capacite]:
            del self._seaux[cle]


_parametres = get_settings()
limiteur_connexion = LimiteurTentatives(
    capacite=_parametres.rate_limit_login_tentatives,
    fenetre=_parametres.rate_limit_login_fenetre_secondes,
)


def _adresse_client(request: Request) -> str:
    return request.client.host if request.client else "inconnu"


def limiter_connexion(request: Request) -> None:
    """Dépendance à poser sur la route de connexion (429 quand l'IP a épuisé ses tentatives)."""
    attente = limiteur_connexion.consommer(_adresse_client(request))
    if attente > 0:
        secondes = max(1, int(attente + 0.999))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives de connexion. Réessayez plus tard.",
            headers={"Retry-After": str(secondes)},
        )
