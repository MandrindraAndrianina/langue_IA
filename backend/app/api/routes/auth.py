"""Authentification : connexion, inscription d'un apprenant, mot de passe oublié (routes publiques)."""

import calendar
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.rate_limit import limiter_connexion
from app.core.security import (
    USAGE_REINITIALISATION,
    creer_jeton_acces,
    creer_jeton_reinitialisation,
    empreinte_mot_de_passe,
    hacher_mot_de_passe,
    lire_jeton,
    verifier_mot_de_passe,
)
from app.models import Abonnement, Apprenant, Formule, Langue, Role, StatutAbonnement, StatutUtilisateur, Utilisateur
from app.schemas.utilisateurs import (
    ApprenantOut,
    ForgotPasswordIn,
    LoginIn,
    RegisterIn,
    ResetPasswordIn,
    TokenOut,
    UtilisateurOut,
)
from app.services.email import envoyer_lien_reinitialisation

router = APIRouter(prefix="/auth", tags=["authentification"])


def _ajouter_mois(depart: date, mois: int) -> date:
    """31 janvier + 1 mois → 28 (ou 29) février."""
    total = depart.month - 1 + mois
    annee, numero_mois = depart.year + total // 12, total % 12 + 1
    return date(annee, numero_mois, min(depart.day, calendar.monthrange(annee, numero_mois)[1]))


@router.post("/login", response_model=TokenOut, dependencies=[Depends(limiter_connexion)])
def login(donnees: LoginIn, db: DbSession) -> TokenOut:
    utilisateur = db.scalar(select(Utilisateur).where(Utilisateur.email == donnees.email))
    # Même réponse pour un e-mail inconnu et un mauvais mot de passe : ne pas révéler les comptes existants
    if utilisateur is None or not verifier_mot_de_passe(donnees.mot_de_passe, utilisateur.mot_de_passe):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou mot de passe incorrect.")
    if utilisateur.statut != StatutUtilisateur.ACTIF:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Compte inactif ou suspendu.")
    return TokenOut(
        access_token=creer_jeton_acces(utilisateur.id_user), utilisateur=UtilisateurOut.model_validate(utilisateur)
    )


@router.post("/register", response_model=ApprenantOut, status_code=status.HTTP_201_CREATED)
def register(donnees: RegisterIn, db: DbSession) -> ApprenantOut:
    """Crée l'apprenant, ses langues et son abonnement à la formule choisie ; il doit ensuite se connecter."""
    if db.scalar(select(Utilisateur.id_user).where(Utilisateur.email == donnees.email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Un compte existe déjà avec cette adresse e-mail.")

    formule = db.get(Formule, donnees.id_formule)
    if formule is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Formule inconnue.")

    codes = list(dict.fromkeys(c.strip().lower() for c in donnees.langues))
    langues = db.scalars(select(Langue).where(Langue.code.in_(codes))).all()
    inconnues = set(codes) - {langue.code for langue in langues}
    if inconnues:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Langue inconnue : {', '.join(sorted(inconnues))}.")
    # Une formule sans langue couvre toutes les langues
    couvertes = {langue.code for langue in formule.langues}
    non_couvertes = [langue.libelle for langue in langues if couvertes and langue.code not in couvertes]
    if non_couvertes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"La formule « {formule.libelle} » ne couvre pas : {', '.join(non_couvertes)}.",
        )

    utilisateur = Utilisateur(
        prenom=donnees.prenom,
        nom=donnees.nom,
        email=donnees.email,
        mot_de_passe=hacher_mot_de_passe(donnees.mot_de_passe),
        role=Role.APPRENANT,
        statut=StatutUtilisateur.ACTIF,
    )
    debut = date.today()
    utilisateur.apprenant = Apprenant(date_naissance=donnees.date_naissance, langues=list(langues))
    utilisateur.apprenant.abonnements.append(
        Abonnement(
            formule=formule,
            date_debut=debut,
            date_fin=_ajouter_mois(debut, formule.duree_mois),
            statut=StatutAbonnement.ACTIF,
            quota_heures=formule.quota_heures,
            quota_ateliers=formule.quota_ateliers,
        )
    )
    db.add(utilisateur)
    db.commit()
    db.refresh(utilisateur)
    return ApprenantOut.depuis(utilisateur)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
def forgot_password(donnees: ForgotPasswordIn, db: DbSession) -> Response:
    """Toujours 204 : la réponse ne révèle pas si un compte existe pour cette adresse."""
    utilisateur = db.scalar(select(Utilisateur).where(Utilisateur.email == donnees.email))
    if utilisateur is not None and utilisateur.statut == StatutUtilisateur.ACTIF:
        jeton = creer_jeton_reinitialisation(utilisateur.id_user, utilisateur.mot_de_passe)
        envoyer_lien_reinitialisation(utilisateur.email, utilisateur.prenom, jeton)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(donnees: ResetPasswordIn, db: DbSession) -> Response:
    """Le lien n'est utilisable qu'une fois : il dépend du mot de passe actuel, qui change ici."""
    lien_invalide = HTTPException(status.HTTP_400_BAD_REQUEST, "Ce lien de réinitialisation est invalide ou a expiré.")
    claims = lire_jeton(donnees.token, USAGE_REINITIALISATION)
    if claims is None:
        raise lien_invalide
    utilisateur = db.get(Utilisateur, int(claims["sub"]))
    if utilisateur is None or claims.get("mdp") != empreinte_mot_de_passe(utilisateur.mot_de_passe):
        raise lien_invalide
    utilisateur.mot_de_passe = hacher_mot_de_passe(donnees.nouveau_mot_de_passe)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
