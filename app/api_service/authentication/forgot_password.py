import hashlib
import logging
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.config import get_settings
from app.db.database import get_db
from app.db.models import PasswordResetToken, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


def _send_reset_email(settings, to_email: str, token: str):
    link = f"{settings.FRONTEND_URL}/set-password?token={token}"
    body = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:20px;">
    <div style="max-width:600px;margin:auto;background:white;border-radius:10px;padding:30px;">
        <h2 style="color:#283e4a;text-align:center;">Reestableix la teva contrasenya</h2>
        <p>Has sol·licitat reestablir la teva contrasenya. L'enllaç és vàlid durant <strong>1 hora</strong>.</p>
        <div style="text-align:center;margin:30px 0;">
            <a href="{link}" style="background:#283e4a;color:white;padding:14px 28px;text-decoration:none;border-radius:8px;font-size:16px;">
                Reestablir contrasenya
            </a>
        </div>
        <p style="font-size:13px;color:#666;">Si no has sol·licitat aquest canvi, pots ignorar aquest correu.</p>
        <hr style="border:0;border-top:1px solid #ddd;margin:20px 0;">
        <p style="font-size:11px;color:#aaa;text-align:center;">© {datetime.now().year} Eina Mapeig Variables</p>
    </div></body></html>
    """
    msg = MIMEText(body, "html")
    msg["Subject"] = "Reestableix la teva contrasenya"
    msg["From"]    = settings.SENDER_EMAIL or settings.SMTP_USER
    msg["To"]      = to_email

    with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("GENERAL/forgot_password.html", {"request": request})


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password_route(
    request: Request,
    recover_email: str = Form(...),
    db: Session = Depends(get_db)
):
    settings = get_settings()

    user = db.query(User).filter(User.email == recover_email).first()
    if not user:
        logger.warning(f"Recuperació: no existeix {recover_email}")
        # No revelamos si el email existe o no (seguridad)
        return templates.TemplateResponse("GENERAL/forgot_password.html", {
            "request": request,
            "success": f"Si el correu existeix, rebràs un missatge en breu."
        })

    # Eliminar tokens previos del usuario
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).delete()

    # Generar nuevo token
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at
    ))
    db.commit()

    try:
        _send_reset_email(settings, recover_email, token)
        logger.info(f"Correu de recuperació enviat a {recover_email}")
    except Exception as e:
        logger.error(f"Error enviant correu a {recover_email}: {e}")
        return templates.TemplateResponse("GENERAL/forgot_password.html", {
            "request": request,
            "error": "Error al servidor de correu. Torna a intentar-ho més tard."
        })

    return templates.TemplateResponse("GENERAL/forgot_password.html", {
        "request": request,
        "success": f"Si el correu existeix, rebràs un missatge en breu."
    })
