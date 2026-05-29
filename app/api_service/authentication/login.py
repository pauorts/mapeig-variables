import logging

from fastapi import APIRouter, Form, Request, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.db.security import verify_password
from app.db.exceptions import NotAuthenticatedException

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("GENERAL/login.html", {"request": request})


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()

    if not email or not verify_password(password, user.password_hash):
        logger.warning(f"Login fallit per: {email}")
        return templates.TemplateResponse("GENERAL/login.html", {
            "request": request,
            "error": "Credencials incorrectes"
        })

    request.session["user_id"]       = user.id
    request.session["username"]      = user.username
    request.session["email"]         = user.email
    request.session["hospital_id"]   = user.hospital_id
    request.session["hospital_name"] = user.hospital.hospital
    request.session["rol"]           = user.rol

    logger.info(f"Login correcte per a: {email} (hospital_id: {user.hospital_id}, rol: {user.rol})")
    return RedirectResponse(url="/select/", status_code=status.HTTP_302_FOUND)


def get_current_user(request: Request) -> dict:
    """Dependencia FastAPI para proteger rutas. Lanza NotAuthenticatedException si no hay sesión."""
    user_id    = request.session.get("user_id")
    hospital_id = request.session.get("hospital_id")

    if not user_id or not hospital_id:
        raise NotAuthenticatedException()

    return {
        "id":          user_id,
        "username":    request.session.get("username"),
        "email":       request.session.get("email"),
        "hospital_id": hospital_id,
        "hospital":    request.session.get("hospital_name"),
        "rol":         request.session.get("rol"),
    }
