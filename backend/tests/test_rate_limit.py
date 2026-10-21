"""Limitation des tentatives de connexion (US131) : seau à jetons et blocage 429."""

from app.core.rate_limit import LimiteurTentatives
from tests.conftest import MOT_DE_PASSE, creer_utilisateur


def _tentative(client, email="inconnu@exemple.com", mot_de_passe="Mauvais2026"):
    return client.post("/api/v1/auth/login", json={"email": email, "mot_de_passe": mot_de_passe})


class TestSeauAJetons:
    def test_autorise_la_rafale_puis_refuse(self):
        limiteur = LimiteurTentatives(capacite=2, fenetre=10)
        assert limiteur.consommer("ip", maintenant=0) == 0
        assert limiteur.consommer("ip", maintenant=0) == 0
        # Seau vide : il faut 1 jeton au rythme de 2 par 10 s, soit 5 s.
        assert limiteur.consommer("ip", maintenant=0) == 5

    def test_se_recharge_avec_le_temps(self):
        limiteur = LimiteurTentatives(capacite=1, fenetre=10)
        assert limiteur.consommer("ip", maintenant=0) == 0
        assert limiteur.consommer("ip", maintenant=5) > 0
        assert limiteur.consommer("ip", maintenant=10) == 0

    def test_compteurs_independants_par_cle(self):
        limiteur = LimiteurTentatives(capacite=1, fenetre=10)
        assert limiteur.consommer("1.1.1.1", maintenant=0) == 0
        assert limiteur.consommer("1.1.1.1", maintenant=0) > 0
        assert limiteur.consommer("2.2.2.2", maintenant=0) == 0

    def test_reinitialisation(self):
        limiteur = LimiteurTentatives(capacite=1, fenetre=10)
        assert limiteur.consommer("ip", maintenant=0) == 0
        assert limiteur.consommer("ip", maintenant=0) > 0
        limiteur.reinitialiser()
        assert limiteur.consommer("ip", maintenant=0) == 0


class TestFiltreConnexion:
    def test_bloque_apres_cinq_tentatives(self, client):
        for _ in range(5):
            assert _tentative(client).status_code == 401
        bloquee = _tentative(client)
        assert bloquee.status_code == 429
        assert "tentatives" in bloquee.json()["detail"].lower()
        assert 1 <= int(bloquee.headers["Retry-After"]) <= 60

    def test_ne_limite_pas_les_autres_routes(self, client):
        for _ in range(5):
            _tentative(client)
        assert _tentative(client).status_code == 429
        # Une lecture publique reste accessible malgré le blocage de /login.
        assert client.get("/api/v1/formules").status_code == 200

    def test_connexion_reussie_sous_la_limite(self, client, db):
        utilisateur = creer_utilisateur(db)
        reponse = client.post("/api/v1/auth/login", json={"email": utilisateur.email, "mot_de_passe": MOT_DE_PASSE})
        assert reponse.status_code == 200
        assert reponse.json()["access_token"]
