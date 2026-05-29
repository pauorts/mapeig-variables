from fastapi import Request, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

templates = Jinja2Templates(directory="app/templates")

class NotAuthenticatedException(HTTPException):
    def __init__(self):
        super().__init__(status_code=401, detail="No autenticado")

def register_exception_handlers(app: FastAPI):
    
    @app.exception_handler(StarletteHTTPException)
    async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
        # Si la ruta no existe (Error 404), mostramos una plantilla visual amigable
        if exc.status_code == 404:
            # Asegúrate de crear un error.html sencillo más adelante
            return templates.TemplateResponse(
                "GENERAL/error.html", 
                {"request": request, "error": "La página que buscas no existe."}, 
                status_code=404
            )
        # Para otros errores, mostramos un HTML básico en lugar de JSON
        return HTMLResponse(
            content=f"<h2>Error {exc.status_code}</h2><p>{exc.detail}</p>", 
            status_code=exc.status_code
        )

    @app.exception_handler(NotAuthenticatedException)
    async def not_authenticated_exception_handler(request: Request, exc: NotAuthenticatedException):
        # Si no está logueado, lo redirigimos a la pantalla de login
        return RedirectResponse(url="/login")
