"""Filtres de sécurité HTTP : en-têtes défensifs (XSS) et contrôle d'origine (CSRF).

L'API s'authentifie par un jeton `Authorization: Bearer` (jamais par cookie). Le risque CSRF
est donc structurellement faible, mais un filtre d'origine est ajouté en défense en profondeur :
un navigateur envoie `Origin`/`Sec-Fetch-Site` sur les écritures intersites, contrairement aux
clients non-navigateur (curl, tests, applications mobiles).
"""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

METHODES_SANS_ECRITURE = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Politique de contenu : l'API ne rend pas de HTML en dehors de /docs (Swagger, servi par CDN).
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'none'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "connect-src 'self'"
)

ENTETES_SECURITE = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class EnTetesSecuriteMiddleware(BaseHTTPMiddleware):
    """Ajoute les en-têtes défensifs à toutes les réponses, y compris les erreurs et /media."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        for nom, valeur in ENTETES_SECURITE.items():
            response.headers.setdefault(nom, valeur)
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class FiltreCsrfMiddleware(BaseHTTPMiddleware):
    """Refuse les écritures issues d'une origine inconnue ou explicitement intersites.

    - `Origin` absent : client non-navigateur, autorisé (le jeton reste exigé par les routes).
    - `Origin` présent : doit être une origine autorisée par CORS ou la même origine que l'API.
    - `Sec-Fetch-Site: cross-site` : refusé même si l'origine est absente.
    """

    def __init__(self, app, origines_autorisees: list[str]) -> None:
        super().__init__(app)
        self.origines_autorisees = {origine.rstrip("/") for origine in origines_autorisees}

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.method not in METHODES_SANS_ECRITURE:
            origine = request.headers.get("origin")
            if origine is not None and not self._origine_autorisee(request, origine):
                return JSONResponse({"detail": "Origine non autorisée."}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Requête intersite refusée."}, status_code=403)
        return await call_next(request)

    def _origine_autorisee(self, request: Request, origine: str) -> bool:
        origine = origine.rstrip("/")
        if origine in self.origines_autorisees:
            return True
        meme_origine = f"{request.url.scheme}://{request.url.netloc}"
        return origine == meme_origine
