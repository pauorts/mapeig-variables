import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import PasswordResetToken, User
from app.db.security import hash_password

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/set-password", response_class=HTMLResponse)
async def show_set_password_page(request: Request, token: str = None):
    return templates.TemplateResponse("GENERAL/set_password.html", {"request": request, "token": token})


@router.post("/set-password", response_class=HTMLResponse)
async def process_set_password(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db)
):
    if not token:
        return templates.TemplateResponse("GENERAL/set_password.html", {
            "request": request,
            "error": "No s'ha proporcionat cap token de seguretat."
        })

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    record = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at.is_(None)
    ).first()

    if not record:
        return templates.TemplateResponse("GENERAL/set_password.html", {
            "request": request,
            "error": "L'enllaç és invàlid o ja s'ha utilitzat prèviament."
        })

    now_utc = datetime.now(timezone.utc)
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now_utc > expires_at:
        db.delete(record)
        db.commit()
        return templates.TemplateResponse("GENERAL/set_password.html", {
            "request": request,
            "error": "L'enllaç ha caducat. Sol·licita'n un de nou."
        })

    user = db.query(User).filter(User.id == record.user_id).first()
    if not user:
        return templates.TemplateResponse("GENERAL/set_password.html", {
            "request": request,
            "error": "Usuari no trobat."
        })

    user.password_hash = hash_password(new_password)
    record.used_at = now_utc
    db.commit()

    logger.info(f"Contrasenya actualitzada per a user_id: {user.id}")
    return templates.TemplateResponse("GENERAL/set_password.html", {
        "request": request,
        "success": "La teva contrasenya s'ha establert correctament! Ja pots iniciar sessió."
    })
