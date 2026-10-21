"""Configuration lue dans les variables d'environnement (fichier .env à la racine, voir .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SECRETS_PAR_DEFAUT = {"changeme", "changeme_super_secret_key_here"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = False

    database_url: str = "postgresql://admin:changeme@localhost:5432/centre_langues"

    # JWT
    secret_key: str = "changeme_super_secret_key_here"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    # Durée de validité du lien « mot de passe oublié »
    reset_token_expire_minutes: int = 60
    # Durée de validité du lien envoyé à un formateur créé par l'administrateur (3 jours)
    invitation_token_expire_minutes: int = 4320

    # Limitation des tentatives de connexion (anti brute force) : N tentatives par IP sur une fenêtre
    rate_limit_login_tentatives: int = 5
    rate_limit_login_fenetre_secondes: int = 60

    # Origines autorisées (frontend), séparées par des virgules dans le .env
    backend_cors_origins: str = "http://localhost:3000"
    # Adresse du frontend, pour les liens envoyés par e-mail
    frontend_url: str = "http://localhost:3000"

    bcrypt_rounds: int = 12

    # Photos de profil : dossier servi en lecture publique sous /media
    media_dir: Path = Path("media")
    photo_taille_max: int = 2 * 1024 * 1024

    # Fuseau des statistiques par jour (inscriptions)
    timezone: str = "Indian/Antananarivo"

    # E-mails : sans SMTP_HOST (ou avec les valeurs d'exemple), le message est écrit dans les journaux
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@centre-langues.mg"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]

    @property
    def smtp_configure(self) -> bool:
        return bool(self.smtp_host) and self.smtp_user not in SECRETS_PAR_DEFAUT | {""}

    @field_validator("frontend_url")
    @classmethod
    def sans_barre_finale(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def secret_obligatoire_en_production(self) -> "Settings":
        if self.environment == "production" and self.secret_key in SECRETS_PAR_DEFAUT:
            raise ValueError("SECRET_KEY doit être changée en production (valeur d'exemple détectée).")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
