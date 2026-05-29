import hashlib
import logging
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.config import get_settings
from app.db.database import get_db
from app.db.models import Hospital, PasswordResetToken, User
from app.db.security import hash_password
from app.api_service.authentication.login import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


def _send_welcome_email(settings, to_email: str, nombre: str, token: str):
    link = f"{settings.FRONTEND_URL}/set-password?token={token}"
    body = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:20px;">
    <div style="max-width:600px;margin:auto;background:white;border-radius:10px;padding:30px;">
        <h2 style="color:#283e4a;text-align:center;">Benvingut/da, {nombre}!</h2>
        <p>Un administrador ha creat el teu compte. Per començar, estableix la teva contrasenya:</p>
        <p><strong>L'enllaç és vàlid durant 7 dies.</strong></p>
        <div style="text-align:center;margin:30px 0;">
            <a href="{link}" style="background:#283e4a;color:white;padding:14px 28px;text-decoration:none;border-radius:8px;font-size:16px;">
                Crear la meva contrasenya
            </a>
        </div>
        <hr style="border:0;border-top:1px solid #ddd;margin:20px 0;">
        <p style="font-size:11px;color:#aaa;text-align:center;">© {datetime.now().year} Eina Mapeig Variables</p>
    </div></body></html>
    """
    msg = MIMEText(body, "html")
    msg["Subject"] = "Invitació - Configura el teu compte"
    msg["From"]    = settings.SENDER_EMAIL or settings.SMTP_USER
    msg["To"]      = to_email

    with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


@router.get("/admin/create-user", response_class=HTMLResponse)
async def create_user_form(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    if current_user.get("rol") not in ("admin", "superadmin"):
        return RedirectResponse(url="/select/", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse("GENERAL/create_user.html", {
        "request": request,
        "user": current_user,
        "roles": ["sanitari", "admin"]
    })


@router.post("/admin/create-user")
async def create_user_submit(
    request: Request,
    email: str = Form(...),
    nombre: str = Form(...),
    rol: str = Form(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.get("rol") not in ("admin", "superadmin"):
        return RedirectResponse(url="/select/", status_code=status.HTTP_302_FOUND)

    settings = get_settings()

    # El usuario nuevo pertenece al mismo hospital que el admin
    hospital_id = current_user.get("hospital_id")

    # Verificar que el email no está ya registrado
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse("GENERAL/create_user.html", {
            "request": request,
            "user": current_user,
            "roles": ["sanitari", "admin"],
            "error": "Aquest correu electrònic ja està registrat."
        })

    # Crear usuario con contraseña temporal (el usuario la cambiará vía el token)
    temp_password = secrets.token_urlsafe(20)
    username = email.split("@")[0]

    new_user = User(
        username=username,
        email=email,
        password_hash=hash_password(temp_password),
        rol=rol,
        hospital_id=hospital_id
    )
    db.add(new_user)
    db.flush()  # para obtener new_user.id antes del commit

    # Token de invitación (7 días)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    db.add(PasswordResetToken(
        user_id=new_user.id,
        token_hash=token_hash,
        expires_at=expires_at
    ))
    db.commit()

    try:
        _send_welcome_email(settings, email, nombre, token)
        logger.info(f"Usuari creat i invitació enviada a {email}")
    except Exception as e:
        logger.error(f"Error enviant correu de benvinguda a {email}: {e}")
        return templates.TemplateResponse("GENERAL/create_user.html", {
            "request": request,
            "user": current_user,
            "roles": ["sanitari", "admin"],
            "error": f"Usuari creat però no s'ha pogut enviar el correu: {e}"
        })

    return templates.TemplateResponse("GENERAL/create_user.html", {
        "request": request,
        "user": current_user,
        "roles": ["sanitari", "admin"],
        "success": f"S'ha creat l'usuari i enviat la invitació a {email}."
    })
