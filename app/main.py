import logging
import os

from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from app.db.exceptions import register_exception_handlers
from app.api_service.authentication.login import router as login_router
from app.api_service.authentication.logout import router as logout_router
from app.api_service.authentication.forgot_password import router as forgot_password_router
from app.api_service.authentication.set_password import router as set_password_router
from app.api_service.authentication.create_user import router as create_user_router
from app.api_service.routers.selection import router as selection_router
from app.api_service.routers.mapeos import router as mapeos_router
from app.api_service.routers.map_variables import router as map_variables_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProxyHeadersMiddleware(BaseHTTPMiddleware):
    """Ajusta el esquema a HTTPS cuando la petición viene detrás de Nginx."""
    async def dispatch(self, request: Request, call_next):
        if request.headers.get("x-forwarded-proto") == "https":
            scope = dict(request.scope)
            scope["scheme"] = "https"
            request = Request(scope, request.receive)
        return await call_next(request)


app = FastAPI(title="Eina Mapeig Variables - Hospital Joan XXIII")

# ── Middlewares (orden: proxy → trusted host → sesión) ───────────────────────
app.add_middleware(ProxyHeadersMiddleware)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*.parcsanitari.local", "localhost", "127.0.0.1", "app", "*"]
)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET_KEY"]
)

# ── Archivos estáticos ────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ── Handlers de error ─────────────────────────────────────────────────────────
register_exception_handlers(app)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(login_router)
app.include_router(logout_router)
app.include_router(forgot_password_router)
app.include_router(set_password_router)
app.include_router(create_user_router)
app.include_router(selection_router,     prefix="/select")
app.include_router(mapeos_router,        prefix="/mapeos")
app.include_router(map_variables_router, prefix="/map_var")


@app.get("/")
def root():
    return RedirectResponse(url="/login")


@app.get("/health")
def health():
    return {"status": "ok"}
