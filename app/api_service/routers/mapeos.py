from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_service.authentication.login import get_current_user
from app.db.database import get_db
from app.services.map_extractor import DashboardService, MapService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


class SelectionRequest(BaseModel):
    ref_ids: List[int]


# ── HTML ──────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def view_maps(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse("VIEW_MAPS/view_maps.html", {
        "request": request,
        "user": user,
    })


# ── API JSON ──────────────────────────────────────────────────────────────────

@router.get("/api/stats")
async def api_stats(
    grupo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    svc = DashboardService(db, user["hospital_id"])
    stats = svc.get_stats(grupo)
    categories = svc.get_categories() if not grupo else None
    payload: dict = {"stats": stats}
    if categories is not None:
        payload["categories"] = categories
    return JSONResponse(payload)


@router.get("/api/vars")
async def api_vars(
    grupo: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    mapped: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    mapped_filter: Optional[bool] = None
    if mapped == "true":
        mapped_filter = True
    elif mapped == "false":
        mapped_filter = False
    svc = DashboardService(db, user["hospital_id"])
    vars_list = svc.get_vars_with_status(grupo=grupo, search=q, mapped_filter=mapped_filter)
    return JSONResponse({"vars": vars_list})


# ── Exports ───────────────────────────────────────────────────────────────────

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/export/mine")
async def export_mine(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    svc = DashboardService(db, user["hospital_id"])
    excel_bytes = svc.export_hospital_excel()
    filename = f"mapeos_{user['hospital'].replace(' ', '_')}.xlsx"
    return Response(
        content=excel_bytes,
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export/mine/selection")
async def export_mine_selection(
    body: SelectionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if not body.ref_ids:
        return JSONResponse({"error": "No s'han seleccionat variables"}, status_code=400)
    svc = DashboardService(db, user["hospital_id"])
    excel_bytes = svc.export_hospital_excel(ref_ids=body.ref_ids)
    hosp = user["hospital"].replace(" ", "_")
    return Response(
        content=excel_bytes,
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="seleccio_{hosp}.xlsx"'},
    )


@router.get("/export/all")
async def export_all(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    svc = DashboardService(db, user["hospital_id"])
    excel_bytes = svc.export_all_hospitals_excel()
    return Response(
        content=excel_bytes,
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="tots_mapeos.xlsx"'},
    )


@router.post("/export/all/selection")
async def export_all_selection(
    body: SelectionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if not body.ref_ids:
        return JSONResponse({"error": "No s'han seleccionat variables"}, status_code=400)
    svc = DashboardService(db, user["hospital_id"])
    excel_bytes = svc.export_all_hospitals_excel(ref_ids=body.ref_ids)
    return Response(
        content=excel_bytes,
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="seleccio_tots_centres.xlsx"'},
    )


# ── Autocomplete (legacy) ─────────────────────────────────────────────────────

@router.get("/autocomplete")
async def autocomplete_reference(term: str = Query("")):
    mapsvc = MapService()
    return JSONResponse(mapsvc.autocomplete_reference(term))
