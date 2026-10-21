"""Tests contre une vraie base PostgreSQL de test (comme en production : unaccent, clés étrangères).

La base `<nom>_test` est créée à côté de celle de DATABASE_URL, migrée par Alembic (la migration est donc
testée aussi), puis vidée avant chaque test. Lancer : `docker compose run --rm backend pytest` (voir README).
"""

import os
import tempfile
from collections.abc import Iterator

from sqlalchemy.engine import make_url

# Configuration de test, à poser AVANT d'importer l'application (la configuration est lue une seule fois)
_url = make_url(os.environ.get("DATABASE_URL", "postgresql://admin:changeme@localhost:5432/centre_langues"))
URL_TEST = _url.set(database=f"{_url.database}_test")
os.environ["DATABASE_URL"] = URL_TEST.render_as_string(hide_password=False)
os.environ["MEDIA_DIR"] = tempfile.mkdtemp(prefix="media-test-")
os.environ["BCRYPT_ROUNDS"] = "4"  # hachage rapide en test
os.environ["SECRET_KEY"] = "cle-de-test"
os.environ.pop("SMTP_HOST", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.rate_limit import limiteur_connexion  # noqa: E402
from app.core.security import creer_jeton_acces, hacher_mot_de_passe  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Administrateur, Apprenant, Formateur, Role, StatutUtilisateur, Utilisateur  # noqa: E402
from app.seed import charger_referentiel  # noqa: E402

MOT_DE_PASSE = "Langue2026"


def _creer_base_de_test() -> None:
    maintenance = create_engine(URL_TEST.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with maintenance.connect() as connexion:
        existe = connexion.scalar(text("SELECT 1 FROM pg_database WHERE datname = :nom"), {"nom": URL_TEST.database})
        if not existe:
            connexion.execute(text(f'CREATE DATABASE "{URL_TEST.database}"'))
    maintenance.dispose()


@pytest.fixture(scope="session", autouse=True)
def base_migree() -> None:
    _creer_base_de_test()
    with engine.begin() as connexion:
        connexion.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
def base_vide(base_migree) -> Iterator[None]:
    """Chaque test part d'une base vide, avec le référentiel (langues, niveaux, formules)."""
    with engine.begin() as connexion:
        tables = connexion.scalars(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
        ).all()
        connexion.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    with SessionLocal() as db:
        charger_referentiel(db)
    limiteur_connexion.reinitialiser()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def creer_utilisateur(
    db: Session,
    role: Role = Role.APPRENANT,
    email: str = "rova@exemple.com",
    prenom: str = "Rova",
    nom: str = "RAKOTO",
    statut: StatutUtilisateur = StatutUtilisateur.ACTIF,
    mot_de_passe: str = MOT_DE_PASSE,
) -> Utilisateur:
    utilisateur = Utilisateur(
        prenom=prenom, nom=nom, email=email, mot_de_passe=hacher_mot_de_passe(mot_de_passe), role=role, statut=statut
    )
    if role == Role.APPRENANT:
        utilisateur.apprenant = Apprenant()
    elif role == Role.FORMATEUR:
        utilisateur.formateur = Formateur()
    else:
        utilisateur.administrateur = Administrateur()
    db.add(utilisateur)
    db.commit()
    return utilisateur


def entete(utilisateur: Utilisateur) -> dict[str, str]:
    return {"Authorization": f"Bearer {creer_jeton_acces(utilisateur.id_user)}"}


@pytest.fixture
def admin(db: Session) -> Utilisateur:
    return creer_utilisateur(db, Role.ADMINISTRATEUR, "admin@digitheque.mg", "Fanja", "RASOA")


@pytest.fixture
def admin_entete(admin: Utilisateur) -> dict[str, str]:
    return entete(admin)
