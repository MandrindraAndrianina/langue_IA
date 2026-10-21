"""Point d'entrée du backend FastAPI : routes /api/v1, photos sous /media, santé sous /health."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.securite import EnTetesSecuriteMiddleware, FiltreCsrfMiddleware

settings = get_settings()

app = FastAPI(
    title="Centre de langues IA — API",
    version="0.1.0",
    description="API du centre de langues La Digithèque (contrat : docs/api/contrat-frontend.md).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Le jeton est envoyé en en-tête Authorization : l'API n'utilise pas de cookie, donc pas de
    # requête « crédentialisée » intersite (défense CSRF).
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(FiltreCsrfMiddleware, origines_autorisees=settings.cors_origins)
app.add_middleware(EnTetesSecuriteMiddleware)

app.include_router(api_router)

# Photos de profil, en lecture publique (le chemin est enregistré dans Utilisateur.photo_url)
(settings.media_dir / "photos").mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")


@app.get("/health", tags=["supervision"])
def health() -> dict[str, str]:
    """Utilisée par le healthcheck Docker et la supervision."""
    return {"status": "ok", "service": "backend"}
