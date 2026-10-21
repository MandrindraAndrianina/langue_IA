"""Administration des formateurs (rôle ADMINISTRATEUR) : liste, création, modification, (dés)activation.

Pas de suppression : un formateur est lié à ses ateliers (ON DELETE RESTRICT), il est désactivé à la place.
"""

import secrets
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import AdministrateurConnecte, DbSession, Pagination
from app.core.config import get_settings
from app.core.security import creer_jeton_reinitialisation, hacher_mot_de_passe
from app.models import Formateur, Langue, Role, StatutUtilisateur, Utilisateur
from app.schemas.formateurs import FormateurCreate, FormateurOut, FormateurUpdate, PageFormateurs
from app.services.email import envoyer_invitation_formateur
from app.services.recherche import contient

router = APIRouter(prefix="/formateurs", tags=["administration des formateurs"])


def _langues(db: Session, id_langues: list[int]) -> list[Langue]:
    """422 si un identifiant ne correspond à aucune langue."""
    ids = list(dict.fromkeys(id_langues))
    langues = db.scalars(select(Langue).where(Langue.id_langue.in_(ids))).all()
    inconnues = set(ids) - {langue.id_langue for langue in langues}
    if inconnues:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Langue inconnue : {', '.join(map(str, sorted(inconnues)))}."
        )
    return list(langues)


def _verifier_email_libre(db: Session, email: str) -> None:
    if db.scalar(select(Utilisateur.id_user).where(Utilisateur.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cette adresse e-mail est déjà utilisée par un autre compte.")


@router.get("", response_model=PageFormateurs)
def lister_formateurs(
    db: DbSession,
    _admin: AdministrateurConnecte,
    pagination: Annotated[Pagination, Depends()],
    search: Annotated[str | None, Query(max_length=100, description="Nom, prénom ou e-mail")] = None,
    statut: StatutUtilisateur | None = None,
) -> PageFormateurs:
    filtres = [Utilisateur.role == Role.FORMATEUR]
    if search and search.strip():
        filtres.append(contient(search, Utilisateur.nom, Utilisateur.prenom, Utilisateur.email))
    if statut is not None:
        filtres.append(Utilisateur.statut == statut)

    total = db.scalar(select(func.count()).select_from(Utilisateur).where(*filtres)) or 0
    items: Sequence[Utilisateur] = db.scalars(
        select(Utilisateur)
        .where(*filtres)
        .options(selectinload(Utilisateur.formateur))
        .order_by(Utilisateur.nom, Utilisateur.prenom, Utilisateur.id_user)
        .offset(pagination.offset)
        .limit(pagination.page_size)
    ).all()
    return PageFormateurs(
        items=[FormateurOut.depuis(u) for u in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("", response_model=FormateurOut, status_code=status.HTTP_201_CREATED)
def creer_formateur(donnees: FormateurCreate, db: DbSession, _admin: AdministrateurConnecte) -> FormateurOut:
    """Le compte est créé sans mot de passe connu : le formateur reçoit un lien pour choisir le sien."""
    _verifier_email_libre(db, donnees.email)
    langues = _langues(db, donnees.id_langues)

    utilisateur = Utilisateur(
        prenom=donnees.prenom,
        nom=donnees.nom,
        email=donnees.email,
        telephone=donnees.telephone,
        # Mot de passe aléatoire jamais communiqué : inutilisable pour se connecter
        mot_de_passe=hacher_mot_de_passe(secrets.token_urlsafe(32)),
        role=Role.FORMATEUR,
        statut=StatutUtilisateur.ACTIF,
    )
    utilisateur.formateur = Formateur(
        type_contrat=donnees.type_contrat, certifications=donnees.certifications, langues_enseignees=langues
    )
    db.add(utilisateur)
    db.commit()
    db.refresh(utilisateur)

    jeton = creer_jeton_reinitialisation(
        utilisateur.id_user, utilisateur.mot_de_passe, get_settings().invitation_token_expire_minutes
    )
    envoyer_invitation_formateur(utilisateur.email, utilisateur.prenom, jeton)
    return FormateurOut.depuis(utilisateur)


@router.patch("/{id_user}", response_model=FormateurOut)
def modifier_formateur(
    id_user: int, donnees: FormateurUpdate, db: DbSession, _admin: AdministrateurConnecte
) -> FormateurOut:
    utilisateur = db.get(Utilisateur, id_user)
    if utilisateur is None or utilisateur.role != Role.FORMATEUR:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formateur introuvable.")
    champs = donnees.model_dump(exclude_unset=True)

    email = champs.get("email")
    if email and email != utilisateur.email:
        _verifier_email_libre(db, email)

    for champ in ("prenom", "nom", "email", "statut"):
        if champs.get(champ) is not None:
            setattr(utilisateur, champ, champs[champ])
    if "telephone" in champs:
        utilisateur.telephone = champs["telephone"]

    if utilisateur.formateur is None:
        utilisateur.formateur = Formateur()
    formateur = utilisateur.formateur
    if champs.get("type_contrat") is not None:
        formateur.type_contrat = champs["type_contrat"]
    if "certifications" in champs:
        formateur.certifications = champs["certifications"]
    if champs.get("id_langues") is not None:
        formateur.langues_enseignees = _langues(db, champs["id_langues"])
    db.commit()
    db.refresh(utilisateur)
    return FormateurOut.depuis(utilisateur)
