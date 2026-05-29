import math
import unicodedata
from collections import defaultdict

import pandas as pd
from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.database import get_db
from app.db.models import VarsLocal, VarsMapped, VarsRef
from app.api_service.authentication.login import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _normalize_str(s: str) -> str:
    if pd.isna(s):
        return ""
    return ''.join(
        c for c in unicodedata.normalize('NFD', str(s))
        if unicodedata.category(c) != 'Mn'
    ).lower()


def _normalize_float(val):
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return None
    return val


def _filter_by_prefix(results):
    """Mantiene solo filas de tablas P_ si existen para ese variable_id; si no, todas."""
    grouped = defaultdict(list)
    for row in results:
        grouped[row.variable_id].append(row)

    final = []
    for var_id, group in grouped.items():
        p_rows = [r for r in group if r.tabla_origen and r.tabla_origen.startswith("P_")]
        final.extend(p_rows if p_rows else group)
    return final


# ── HTML ──────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def render_map_var(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse("MAP_VARS/mapeo_variables.html", {"request": request, "user": user})


# ── Categorías ────────────────────────────────────────────────────────────────

@router.get("/variables/categorias/{tipo}")
def get_variable_categories(
    tipo: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    hospital_id = user["hospital_id"]
    is_super    = user.get("rol") == "superadmin"

    if tipo == "hospital":
        q = (
            db.query(VarsLocal.origen_variable)
            .filter(VarsLocal.origen_variable.isnot(None))
        )
        if not is_super:
            q = q.filter(VarsLocal.hospital_id == hospital_id)
        rows = q.distinct().all()
        cats = [r[0] for r in rows]
    else:
        rows = (
            db.query(VarsRef.grupo)
            .filter(VarsRef.grupo.isnot(None))
            .distinct()
            .all()
        )
        cats = [r[0] for r in rows]

    invalidos = {"nan", "none", "None", "Nan", ""}
    return {"categorias": [c for c in cats if c and str(c).strip() not in invalidos]}


# ── Variables del hospital ────────────────────────────────────────────────────

@router.get("/variables/hospital/{variableid}")
def get_variables_by_variableid(
    variableid: int,
    tabla: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    user_id     = user["id"]
    hospital_id = user["hospital_id"]
    is_super    = user.get("rol") == "superadmin"

    filters = [
        VarsLocal.variable_id == variableid,
        VarsLocal.tabla_origen == tabla,
    ]
    if not is_super:
        filters.append(VarsLocal.hospital_id == hospital_id)

    variables = (
        db.query(VarsLocal)
        .options(
            selectinload(VarsLocal.mappings).options(
                joinedload(VarsMapped.user),
                joinedload(VarsMapped.variable_referencia),
            )
        )
        .filter(*filters)
        .all()
    )

    return JSONResponse([_serialize_local(v, user_id) for v in variables])


@router.get("/variables/hospital")
def get_hospital_variables(
    tipo: str = None,
    search: str = None,
    exacta: str = "NO",
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    user_id     = user["id"]
    hospital_id = user["hospital_id"]
    is_super    = user.get("rol") == "superadmin"

    query = (
        db.query(VarsLocal)
        .options(
            selectinload(VarsLocal.mappings).options(
                joinedload(VarsMapped.user),
                joinedload(VarsMapped.variable_referencia),
            )
        )
    )
    if not is_super:
        query = query.filter(VarsLocal.hospital_id == hospital_id)

    if tipo:
        query = query.filter(VarsLocal.origen_variable == tipo)

    if search:
        col = func.unaccent(func.lower(VarsLocal.description))
        term = _normalize_str(search.strip())
        query = query.filter(col.ilike(term) if exacta == "SI" else col.ilike(f"%{term}%"))

    results = _filter_by_prefix(query.all())
    return JSONResponse([_serialize_local(v, user_id) for v in results])


def _serialize_local(v: VarsLocal, user_id: int) -> dict:
    first_map = v.mappings[0] if v.mappings else None
    ref = first_map.variable_referencia if first_map else None
    return {
        "id":            v.id,
        "variableid":    v.variable_id,
        "value":         v.value,
        "nombre":        v.description,
        "clave":         v.clave,
        "tipo":          v.tipo_variable,
        "origen":        v.origen_variable,
        "last_value":    v.last_value.isoformat() if v.last_value else None,
        "count":         v.count,
        "q1":            _normalize_float(v.q1),
        "q2":            _normalize_float(v.q2),
        "q3":            _normalize_float(v.q3),
        "porc_pats":     _normalize_float(v.porc_pats),
        "cadencia":      v.cadencia,
        "codigo":        v.codigo,
        "tabla_origen":  v.tabla_origen,
        "mapeada":       any(m.user_id == user_id for m in v.mappings),
        "ref_pk":        first_map.ref_pk if first_map else None,
        "snomed_id":     ref.snomed_id if ref else None,
        "snomed_name":   ref.variable if ref else None,
        "fecha_mapeo":   first_map.created_at.isoformat() if first_map else None,
        "usuario_mapeo": first_map.user.username if first_map and first_map.user else None,
    }


# ── Variables de referencia (catálogo SOCMIC/openEHR) ────────────────────────

@router.get("/variables/reference/{ref_id}")
def get_reference_variable_by_id(
    ref_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    v = (
        db.query(VarsRef)
        .options(joinedload(VarsRef.mappings).joinedload(VarsMapped.local_variable))
        .filter(VarsRef.id == ref_id)
        .first()
    )
    if not v:
        return JSONResponse({"error": "Variable no trobada"}, status_code=404)
    return JSONResponse(_serialize_ref(v))


@router.get("/variables/reference")
def get_reference_variables(
    tipo: str = None,
    search: str = None,
    exacta: str = "NO",
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    user_id = user["id"]

    query = (
        db.query(VarsRef)
        .options(joinedload(VarsRef.mappings).joinedload(VarsMapped.local_variable))
    )

    if tipo:
        query = query.filter(VarsRef.grupo == tipo)

    if search:
        term = _normalize_str(search.strip())
        col_nombre_openehr    = func.unaccent(func.lower(VarsRef.openehr_nombre))
        col_categoria_openehr = func.unaccent(func.lower(VarsRef.openehr_categoria))
        col_categoria_socmic  = func.unaccent(func.lower(VarsRef.descripcion_socmic))
        col_nombre_socmic     = func.unaccent(func.lower(VarsRef.variable))
        col_nombre_snomed     = func.unaccent(func.lower(VarsRef.snomed_term))
        if exacta == "SI":
            query = query.filter(or_(
                col_nombre_openehr.ilike(term),
                col_categoria_openehr.ilike(term),
                col_categoria_socmic.ilike(term),
                col_nombre_socmic.ilike(term),
                col_nombre_snomed.ilike(term),
            ))
        else:
            query = query.filter(or_(
                col_nombre_openehr.ilike(f"%{term}%"),
                col_categoria_openehr.ilike(f"%{term}%"),
                col_categoria_socmic.ilike(f"%{term}%"),
                col_nombre_socmic.ilike(f"%{term}%"),
                col_nombre_snomed.ilike(f"%{term}%"),
            ))

    results = query.all()
    return JSONResponse([_serialize_ref(v) for v in results])


def _serialize_ref(v: VarsRef) -> dict:
    first_map = v.mappings[0] if v.mappings else None
    return {
        "id":        v.id,
        "snomed_id":         v.snomed_id,
        "nombre":            v.variable,
        "nombre_snomed":     v.snomed_term,
        "nombre_openEHR":    v.openehr_nombre,
        "categoria_socmic":  v.grupo,
        "tipo_var":          v.tipo_variable,
        "tipo_snomed":       v.snomed_categoria,
        "tipo_openEHR":      v.openehr_tipo_var,
        "origen":            v.openehr_tipo_dato,
        "unidad":            v.unidad_ucum,
        "descripcion":       v.descripcion_socmic,
        "descripcion_openEHR": v.openehr_descripcion,
        "icd":               v.icd10_code,
        "categoria_openEHR": v.openehr_categoria,
        "local_pk":          first_map.local_pk if first_map else None,
        "local_description": first_map.local_variable.description if first_map and first_map.local_variable else None,
        "fecha_mapeo":       first_map.created_at.isoformat() if first_map else None,
        "usuario_mapeo":     first_map.user_id if first_map else None,
    }


# ── Mapear ────────────────────────────────────────────────────────────────────

@router.post("/mapear")
def create_mapping(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    reference_var    = payload.get("reference_var")
    hospital_vars = payload.get("hospital_vars")

    if not reference_var or not hospital_vars:
        return JSONResponse({"error": "Faltan datos de las variables"}, status_code=400)

    resultados = []
    for var in hospital_vars:
        try:
            new_map = VarsMapped(
                local_pk = var.get("id"),
                ref_pk   = reference_var.get("id"),
                user_id  = user["id"],
            )
            db.add(new_map)
            db.commit()
            db.refresh(new_map)

            resultados.append({
                "id":           new_map.id,
                "snomed_name":  reference_var.get("nombre"),
                "fecha_mapeo":  new_map.created_at.isoformat(),
            })

        except Exception as e:
            db.rollback()
            return JSONResponse({"error": f"Error creant mapeig: {str(e)}"}, status_code=500)

    return JSONResponse({"msg": "Mapejos creats correctament.", "resultats": resultados})


# ── Desmapear ─────────────────────────────────────────────────────────────────

@router.delete("/desmapear")
def delete_mapping(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    var     = payload.get("v")
    tipo    = payload.get("type")
    user_id = user["id"]

    if tipo == "reference":
        mappings = db.query(VarsMapped).filter(
            and_(VarsMapped.ref_pk == var.get("variableid"), VarsMapped.user_id == user_id)
        ).all()
    else:
        mappings = db.query(VarsMapped).filter(
            and_(VarsMapped.local_pk == var.get("id"), VarsMapped.user_id == user_id)
        ).all()

    if not mappings:
        return JSONResponse({"error": "No se encontró el mapeo"}, status_code=404)

    for m in mappings:
        db.delete(m)
    db.commit()

    return JSONResponse({"msg": "Mapeo eliminado correctamente"})
