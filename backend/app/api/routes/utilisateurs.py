"""Administration des utilisateurs (rôle ADMINISTRATEUR) : liste, modification, (dés)activation."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import AdministrateurConnecte, DbSession, Pagination
from app.models import Administrateur, Apprenant, Formateur, Role, StatutUtilisateur, Utilisateur
from app.schemas.utilisateurs import PageUtilisateurs, UtilisateurAdminUpdate, UtilisateurOut
from app.services.recherche import contient

router = APIRouter(prefix="/users", tags=["administration des utilisateurs"])


def _assurer_specialisation(utilisateur: Utilisateur, role: Role) -> None:
    """Crée la ligne Apprenant / Formateur / Administrateur du nouveau rôle si elle n'existe pas encore."""
    if role == Role.APPRENANT and utilisateur.apprenant is None:
        utilisateur.apprenant = Apprenant()
    elif role == Role.FORMATEUR and utilisateur.formateur is None:
        utilisateur.formateur = Formateur()
    elif role == Role.ADMINISTRATEUR and utilisateur.administrateur is None:
        utilisateur.administrateur = Administrateur()


@router.get("", response_model=PageUtilisateurs)
def lister_utilisateurs(
    db: DbSession,
    _admin: AdministrateurConnecte,
    pagination: Annotated[Pagination, Depends()],
    search: Annotated[str | None, Query(max_length=100, description="Nom, prénom ou e-mail")] = None,
    role: Role | None = None,
) -> PageUtilisateurs:
    filtres = []
    if search and search.strip():
        filtres.append(contient(search, Utilisateur.nom, Utilisateur.prenom, Utilisateur.email))
    if role is not None:
        filtres.append(Utilisateur.role == role)

    total = db.scalar(select(func.count()).select_from(Utilisateur).where(*filtres)) or 0
    items = db.scalars(
        select(Utilisateur)
        .where(*filtres)
        .order_by(Utilisateur.nom, Utilisateur.prenom, Utilisateur.id_user)
        .offset(pagination.offset)
        .limit(pagination.page_size)
    ).all()
    return PageUtilisateurs(
        items=[UtilisateurOut.model_validate(u) for u in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.patch("/{id_user}", response_model=UtilisateurOut)
def modifier_utilisateur(
    id_user: int, donnees: UtilisateurAdminUpdate, db: DbSession, admin: AdministrateurConnecte
) -> Utilisateur:
    utilisateur = db.get(Utilisateur, id_user)
    if utilisateur is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur introuvable.")
    champs = donnees.model_dump(exclude_unset=True)

    if utilisateur.id_user == admin.id_user:
        if champs.get("role") not in (None, admin.role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Vous ne pouvez pas modifier votre propre rôle.")
        if champs.get("statut") not in (None, StatutUtilisateur.ACTIF):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Vous ne pouvez pas désactiver votre propre compte.")

    email = champs.get("email")
    if email and email != utilisateur.email:
        if db.scalar(select(Utilisateur.id_user).where(Utilisateur.email == email)) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Cette adresse e-mail est déjà utilisée par un autre compte.")

    for champ in ("prenom", "nom", "email", "statut"):
        if champs.get(champ) is not None:
            setattr(utilisateur, champ, champs[champ])
    if "telephone" in champs:
        utilisateur.telephone = champs["telephone"]
    if champs.get("role") is not None:
        utilisateur.role = champs["role"]
        _assurer_specialisation(utilisateur, champs["role"])
    db.commit()
    return utilisateur
