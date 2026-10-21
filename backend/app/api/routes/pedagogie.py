"""Langues et niveaux (rôle ADMINISTRATEUR), avec l'association LangueNiveau."""

from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AdministrateurConnecte, DbSession, Pagination
from app.models import Langue, Niveau
from app.schemas.pedagogie import LangueAvecNiveauxOut, LangueCreate, LangueUpdate, NiveauIn, NiveauOut, PageLangues
from app.services.recherche import contient

router = APIRouter(tags=["langues et niveaux"])


def _niveaux(db: Session, ids: list[int]) -> list[Niveau]:
    """Niveaux demandés ; 422 si l'un d'eux n'existe pas."""
    ids_uniques = list(dict.fromkeys(ids))
    niveaux = db.scalars(select(Niveau).where(Niveau.id_niveau.in_(ids_uniques))).all()
    if len(niveaux) != len(ids_uniques):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Niveau inconnu.")
    return list(niveaux)


def _code_langue_libre(db: Session, code: str, id_langue: int | None = None) -> None:
    existant = db.scalar(select(Langue.id_langue).where(Langue.code == code))
    if existant is not None and existant != id_langue:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce code est déjà utilisé par une autre langue.")


def _code_niveau_libre(db: Session, code: str, id_niveau: int | None = None) -> None:
    existant = db.scalar(select(Niveau.id_niveau).where(Niveau.code == code))
    if existant is not None and existant != id_niveau:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce code est déjà utilisé par un autre niveau.")


# ----- Langues -----


@router.get("/langues", response_model=PageLangues)
def lister_langues(
    db: DbSession,
    _admin: AdministrateurConnecte,
    pagination: Annotated[Pagination, Depends()],
    search: Annotated[str | None, Query(max_length=100, description="Désignation ou code")] = None,
) -> PageLangues:
    filtres = [contient(search, Langue.libelle, Langue.code)] if search and search.strip() else []
    total = db.scalar(select(func.count()).select_from(Langue).where(*filtres)) or 0
    langues = db.scalars(
        select(Langue).where(*filtres).order_by(Langue.libelle).offset(pagination.offset).limit(pagination.page_size)
    ).all()
    return PageLangues(
        items=[LangueAvecNiveauxOut.model_validate(langue) for langue in langues],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("/langues", response_model=LangueAvecNiveauxOut, status_code=status.HTTP_201_CREATED)
def creer_langue(donnees: LangueCreate, db: DbSession, _admin: AdministrateurConnecte) -> Langue:
    _code_langue_libre(db, donnees.code)
    langue = Langue(code=donnees.code, libelle=donnees.libelle, niveaux=_niveaux(db, donnees.id_niveaux))
    db.add(langue)
    db.commit()
    return langue


@router.patch("/langues/{id_langue}", response_model=LangueAvecNiveauxOut)
def modifier_langue(id_langue: int, donnees: LangueUpdate, db: DbSession, _admin: AdministrateurConnecte) -> Langue:
    langue = db.get(Langue, id_langue)
    if langue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Langue introuvable.")
    if donnees.code is not None:
        _code_langue_libre(db, donnees.code, id_langue)
        langue.code = donnees.code
    if donnees.libelle is not None:
        langue.libelle = donnees.libelle
    if donnees.id_niveaux is not None:
        # Remplace toute la liste : les lignes LangueNiveau sont ajoutées ou supprimées
        langue.niveaux = _niveaux(db, donnees.id_niveaux)
    db.commit()
    return langue


@router.delete("/langues/{id_langue}", status_code=status.HTTP_204_NO_CONTENT)
def supprimer_langue(id_langue: int, db: DbSession, _admin: AdministrateurConnecte) -> Response:
    langue = db.get(Langue, id_langue)
    if langue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Langue introuvable.")
    db.delete(langue)
    try:
        db.commit()
    except IntegrityError:
        # Clé étrangère RESTRICT : langue d'une formule, d'un apprenant, d'un formateur ou d'un atelier
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cette langue est utilisée (formules, apprenants, ateliers) : suppression refusée.",
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----- Niveaux -----


@router.get("/niveaux", response_model=list[NiveauOut])
def lister_niveaux(db: DbSession, _admin: AdministrateurConnecte) -> Sequence[Niveau]:
    return db.scalars(select(Niveau).order_by(Niveau.code)).all()


@router.post("/niveaux", response_model=NiveauOut, status_code=status.HTTP_201_CREATED)
def creer_niveau(donnees: NiveauIn, db: DbSession, _admin: AdministrateurConnecte) -> Niveau:
    _code_niveau_libre(db, donnees.code)
    niveau = Niveau(code=donnees.code, libelle=donnees.libelle)
    db.add(niveau)
    db.commit()
    return niveau


@router.patch("/niveaux/{id_niveau}", response_model=NiveauOut)
def modifier_niveau(id_niveau: int, donnees: NiveauIn, db: DbSession, _admin: AdministrateurConnecte) -> Niveau:
    niveau = db.get(Niveau, id_niveau)
    if niveau is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Niveau introuvable.")
    _code_niveau_libre(db, donnees.code, id_niveau)
    niveau.code, niveau.libelle = donnees.code, donnees.libelle
    db.commit()
    return niveau


@router.delete("/niveaux/{id_niveau}", status_code=status.HTTP_204_NO_CONTENT)
def supprimer_niveau(id_niveau: int, db: DbSession, _admin: AdministrateurConnecte) -> Response:
    """Les lignes LangueNiveau sont supprimées en cascade ; 409 si un autre objet utilise le niveau."""
    niveau = db.get(Niveau, id_niveau)
    if niveau is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Niveau introuvable.")
    db.delete(niveau)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce niveau est utilisé : suppression refusée.") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
