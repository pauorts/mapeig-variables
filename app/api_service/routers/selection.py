from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api_service.authentication.login import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def selection_page(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse("SELECT/selection.html", {"request": request, "user": user})
