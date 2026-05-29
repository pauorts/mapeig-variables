import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/logout")
async def logout(request: Request):
    user = request.session.get("username", "desconocido")
    request.session.clear()
    logger.info(f"Sessió tancada per: {user}")
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
