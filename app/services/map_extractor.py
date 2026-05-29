import io
import logging
import math
import unicodedata
from collections import defaultdict
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session, joinedload

from app.db.database import SessionLocal
from app.db.models import VarsMapped, VarsRef, User

logger = logging.getLogger(__name__)


def _normalize_str(s: str) -> str:
    if pd.isna(s):
        return ""
    return ''.join(
        c for c in unicodedata.normalize('NFD', str(s))
        if unicodedata.category(c) != 'Mn'
    ).lower()


class MapService:
    def __init__(self):
        db: Session = SessionLocal()
        try:
            maps = (
                db.query(VarsMapped)
                .options(
                    joinedload(VarsMapped.user).joinedload(User.hospital),
                    joinedload(VarsMapped.local_variable),
                    joinedload(VarsMapped.variable_referencia),
                )
                .all()
            )

            columns = [
                "ref_pk", "snomed_id", "local_id", "local_value",
                "local_description", "snomed_name", "fecha_mapeo",
                "username", "hospital_name", "tipo_variable", "origen_variable",
                "q1", "q2", "q3", "porc_pats", "cadencia"
            ]

            if not maps:
                self.df_maps = pd.DataFrame(columns=columns)
                return

            self.df_maps = pd.DataFrame([
                {
                    "snomed_id":         m.variable_referencia.snomed_id if m.variable_referencia else None,
                    "local_id":          m.local_variable.variable_id if m.local_variable else None,
                    "local_value":       m.local_variable.value if m.local_variable else None,
                    "local_description": m.local_variable.description if m.local_variable else None,
                    "socmic_name":       m.variable_referencia.variable if m.variable_referencia else None,
                    "snomed_name":       m.variable_referencia.snomed_term if m.variable_referencia else None,
                    "openehr_name":      m.variable_referencia.openehr_nombre if m.variable_referencia else None,
                    "fecha_mapeo":       m.created_at,
                    "user_map":          m.user.username if m.user else "desconocido",
                    "hospital_name":     m.user.hospital.hospital if m.user and m.user.hospital else "Desconegut",
                    "tipo_variable_local":     m.local_variable.tipo_variable if m.local_variable else None,
                    "origen_variable":   m.local_variable.origen_variable if m.local_variable else None,
                    "q1":                m.local_variable.q1 if m.local_variable else None,
                    "q2":                m.local_variable.q2 if m.local_variable else None,
                    "q3":                m.local_variable.q3 if m.local_variable else None,
                    "porc_pats":         m.local_variable.porc_pats if m.local_variable else None,
                    "cadencia":          m.local_variable.cadencia if m.local_variable else None,
                    "icd":               m.local_variable.codigo if m.local_variable else None,
                    "categoria_socmic":  m.variable_referencia.grupo if m.variable_referencia else None,
                    "tipo_variable_socmic":        m.variable_referencia.tipo_variable if m.variable_referencia else None,
                    "icd_snomed":        m.variable_referencia.icd10_code if m.variable_referencia else None,
                    "unidad_ucum":       m.variable_referencia.unidad_ucum if m.variable_referencia else None,
                    "unidad_openehr":    m.variable_referencia.unidad_openehr if m.variable_referencia else None,
                    "openehr_tipo_dato": m.variable_referencia.openehr_tipo_dato if m.variable_referencia else None,
                    "openehr_tipo_var":  m.variable_referencia.openehr_tipo_var if m.variable_referencia else None,
                    "openehr_categoria": m.variable_referencia.openehr_categoria if m.variable_referencia else None,
                }
                for m in maps
            ])

            self.df_maps["socmic_name_norm"] = self.df_maps["socmic_name"].apply(_normalize_str)

        finally:
            db.close()

    def autocomplete_reference(self, term: str):
        if self.df_maps.empty or not term:
            return []
        term_norm = _normalize_str(term)
        df = self.df_maps[self.df_maps["socmic_name_norm"].str.contains(term_norm, na=False)]
        return sorted(df["socmic_name"].unique().tolist())

    def search_by_reference(self, term: str):
        if self.df_maps.empty:
            return []
        term_norm = _normalize_str(term)
        df = self.df_maps[self.df_maps["socmic_name_norm"] == term_norm]
        return self._process_for_display(df.to_dict(orient="records"))

    @staticmethod
    def _process_for_display(results: list) -> list:
        """Agrupa variables categóricas (contienen '|' en local_description)."""
        final_list = []
        groups = {}

        for m in results:
            # Normalizar NaN/fechas
            for k, v in m.items():
                if isinstance(v, float) and math.isnan(v):
                    m[k] = None
                elif k == "fecha_mapeo" and v:
                    m[k] = str(v)

            name      = m.get("local_description", "") or ""
            username  = m.get("username", "")
            tipo      = m.get("grupo", "")

            if tipo == "Categòrica" and "|" in name:
                category, real_name = name.split("|", 1)
                key = (username, real_name)
                if key not in groups:
                    groups[key] = {
                        "is_group":        True,
                        "display_name":    real_name,
                        "local_description": real_name,
                        "username":        username,
                        "sub_items":       []
                    }
                m_copy = m.copy()
                m_copy["category_label"] = category
                groups[key]["sub_items"].append(m_copy)
            else:
                m_copy = m.copy()
                m_copy["is_group"] = False
                final_list.append(m_copy)

        for g in groups.values():
            g["sub_items"].sort(key=lambda x: x.get("category_label", ""))
            final_list.append(g)

        final_list.sort(key=lambda x: x.get("username", ""))
        return final_list


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD SERVICE — cobertura de mapeos por hospital
# ══════════════════════════════════════════════════════════════════════════════

class DashboardService:
    """
    Queries coverage stats for a specific hospital.
    Uses injected db session (FastAPI Depends pattern).
    """

    def __init__(self, db: Session, hospital_id: int):
        self.db = db
        self.hospital_id = hospital_id
        self._my_user_ids = self._load_user_ids()
        self._my_mapped_ref_ids = self._load_mapped_ref_ids()

    def _load_user_ids(self) -> set:
        rows = (
            self.db.query(User.id)
            .filter(User.hospital_id == self.hospital_id)
            .all()
        )
        return {row[0] for row in rows}

    def _load_mapped_ref_ids(self) -> set:
        if not self._my_user_ids:
            return set()
        rows = (
            self.db.query(VarsMapped.ref_pk)
            .filter(VarsMapped.user_id.in_(self._my_user_ids))
            .distinct()
            .all()
        )
        return {row[0] for row in rows}

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self, grupo: Optional[str] = None) -> dict:
        query = self.db.query(VarsRef.id)
        if grupo:
            query = query.filter(VarsRef.grupo == grupo)
        all_ref_ids = {row[0] for row in query.all()}
        total = len(all_ref_ids)
        mapped = len(self._my_mapped_ref_ids & all_ref_ids)
        unmapped = total - mapped
        pct = round(mapped / total * 100, 1) if total > 0 else 0.0
        return {
            "total": total,
            "mapped": mapped,
            "unmapped": unmapped,
            "percentage": pct,
        }

    def get_categories(self) -> list:
        rows = (
            self.db.query(VarsRef.id, VarsRef.grupo)
            .filter(VarsRef.grupo.isnot(None))
            .all()
        )
        tipo_stats: dict = {}
        for ref_id, tipo in rows:
            if tipo not in tipo_stats:
                tipo_stats[tipo] = {"total": 0, "mapped": 0}
            tipo_stats[tipo]["total"] += 1
            if ref_id in self._my_mapped_ref_ids:
                tipo_stats[tipo]["mapped"] += 1

        result = []
        for tipo in sorted(tipo_stats):
            s = tipo_stats[tipo]
            total = s["total"]
            mapped = s["mapped"]
            result.append({
                "tipo": tipo,
                "total": total,
                "mapped": mapped,
                "unmapped": total - mapped,
                "percentage": round(mapped / total * 100, 1) if total > 0 else 0.0,
            })
        return result

    # ── Variable checklist ────────────────────────────────────────────────────

    def get_vars_with_status(
        self,
        grupo: Optional[str] = None,
        search: Optional[str] = None,
        mapped_filter: Optional[bool] = None,
    ) -> list:
        query = self.db.query(VarsRef)
        if grupo:
            query = query.filter(VarsRef.grupo == grupo)

        vars_refs = query.order_by(VarsRef.variable).all()

        if search:
            sl = search.lower()
            vars_refs = [v for v in vars_refs if sl in (v.variable or "").lower()]

        if mapped_filter is True:
            vars_refs = [v for v in vars_refs if v.id in self._my_mapped_ref_ids]
        elif mapped_filter is False:
            vars_refs = [v for v in vars_refs if v.id not in self._my_mapped_ref_ids]

        if not vars_refs:
            return []

        ref_ids = [v.id for v in vars_refs]

        all_mappings = (
            self.db.query(VarsMapped)
            .options(
                joinedload(VarsMapped.local_variable),
                joinedload(VarsMapped.user).joinedload(User.hospital),
            )
            .filter(VarsMapped.ref_pk.in_(ref_ids))
            .all()
        )

        mappings_by_ref: dict = defaultdict(list)
        for m in all_mappings:
            mappings_by_ref[m.ref_pk].append(m)

        result = []
        for v in vars_refs:
            is_mapped = v.id in self._my_mapped_ref_ids
            my_mappings, other_mappings = [], []

            for m in mappings_by_ref[v.id]:
                loc = m.local_variable
                info = {
                    "id": m.id,
                    "local_description": loc.description if loc else None,
                    "local_id": loc.variable_id if loc else None,
                    "tipo_local": loc.tipo_variable if loc else None,
                    "origen_variable": loc.origen_variable if loc else None,
                    "count": loc.count if loc else None,
                    "q1": loc.q1 if loc else None,
                    "q2": loc.q2 if loc else None,
                    "q3": loc.q3 if loc else None,
                    "porc_pats": loc.porc_pats if loc else None,
                    "cadencia": loc.cadencia if loc else None,
                    "hospital_id": m.user.hospital_id if m.user else None,
                    "username": m.user.username if m.user else None,
                    "hospital_name": m.user.hospital.hospital if m.user and m.user.hospital else None,
                    "hospital_acronim": m.user.hospital.acronim if m.user and m.user.hospital else None,
                    "created_at": str(m.created_at)[:10] if m.created_at else None,
                    "validado": m.validado,
                }
                if m.user_id in self._my_user_ids:
                    my_mappings.append(info)
                else:
                    other_mappings.append(info)

            result.append({
                "id": v.id,
                "variable": v.variable,
                "tipo_variable": v.tipo_variable,
                "grupo": v.grupo,
                "descripcion_socmic": v.descripcion_socmic,
                "snomed_id": v.snomed_id,
                "snomed_term": v.snomed_term,
                "snomed_categoria": v.snomed_categoria,
                "icd10_code": v.icd10_code,
                "arquetipo_id": v.arquetipo_id,
                "at_code": v.at_code,
                "openehr_nombre": v.openehr_nombre,
                "openehr_categoria": v.openehr_categoria,
                "openehr_tipo_dato": v.openehr_tipo_dato,
                "unidad_ucum": v.unidad_ucum,
                "unidad_openehr": v.unidad_openehr,
                "is_mapped": is_mapped,
                "my_mappings": my_mappings,
                "other_mappings": other_mappings,
                "total_mappings": len(my_mappings) + len(other_mappings),
                "unique_hospital_count": len({
                    info["hospital_id"]
                    for info in (my_mappings + other_mappings)
                    if info["hospital_id"] is not None
                }),
            })

        return result

    # ── Excel exports ─────────────────────────────────────────────────────────

    def export_hospital_excel(self, ref_ids: Optional[list] = None) -> bytes:
        """Export my hospital's mappings. If ref_ids provided, only those reference variables."""
        rows = []
        if self._my_user_ids:
            query = (
                self.db.query(VarsMapped)
                .options(
                    joinedload(VarsMapped.local_variable),
                    joinedload(VarsMapped.variable_referencia),
                    joinedload(VarsMapped.user),
                )
                .filter(VarsMapped.user_id.in_(self._my_user_ids))
            )
            if ref_ids:
                query = query.filter(VarsMapped.ref_pk.in_(ref_ids))
            for m in query.all():
                ref = m.variable_referencia
                loc = m.local_variable
                rows.append({
                    "Variable Referència":    ref.variable if ref else None,
                    "Grup SOCMIC":            ref.grupo if ref else None,
                    "Tipus referencia":       ref.tipo_variable if ref else None,
                    "SNOMED ID":              ref.snomed_id if ref else None,
                    "SNOMED Term":            ref.snomed_term if ref else None,
                    "openEHR Nom":            ref.openehr_nombre if ref else None,
                    "Unitat UCUM":            ref.unidad_ucum if ref else None,
                    "Unitat openEHR":            ref.unidad_openehr if ref else None,
                    "Tipo dato openEHR":            ref.openehr_tipo_dato if ref else None,
                    "Arquetipo openEHR":            ref.openehr_categoria if ref else None,
                    "Variable Local Hospital": loc.description if loc else None,
                    "Tipus Local":            loc.tipo_variable if loc else None,
                    "Origen":                 loc.origen_variable if loc else None,
                    "VariableID":                 loc.variable_id if loc else None,
                    "Value":                 loc.value if loc else None,
                    "Clave":                 loc.clave if loc else None,
                    "Tabla Sistema":                 loc.tabla_origen if loc else None,
                    "Data Mapeo":             str(m.created_at)[:10] if m.created_at else None,
                    "Validat":                "Sí" if m.validado else "No",
                    "Usuari":                 m.user.username if m.user else None,
                })

        df = pd.DataFrame(rows)
        buf = io.BytesIO()
        sheet = "Selecció Hospital" if ref_ids else "Mapeos Hospital"
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet, index=False)
        buf.seek(0)
        return buf.getvalue()

    def export_all_hospitals_excel(self, ref_ids: Optional[list] = None) -> bytes:
        """Export all hospitals' mappings. If ref_ids provided, only those reference variables."""
        query = (
            self.db.query(VarsMapped)
            .options(
                joinedload(VarsMapped.local_variable),
                joinedload(VarsMapped.variable_referencia),
                joinedload(VarsMapped.user).joinedload(User.hospital),
            )
        )
        if ref_ids:
            query = query.filter(VarsMapped.ref_pk.in_(ref_ids))

        rows = []
        for m in query.all():
            ref = m.variable_referencia
            loc = m.local_variable
            hosp = m.user.hospital if m.user else None
            rows.append({
                "Variable Referència": ref.variable if ref else None,
                "Grup SOCMIC":        ref.grupo if ref else None,
                "Tipus referencia":   ref.tipo_variable if ref else None,
                "SNOMED ID":          ref.snomed_id if ref else None,
                "SNOMED Term":        ref.snomed_term if ref else None,
                "Hospital":           hosp.hospital if hosp else None,
                "Acrònim":            hosp.acronim if hosp else None,
                "Variable Local":     loc.description if loc else None,
                "Tipus Local":        loc.tipo_variable if loc else None,
                "Origen":             loc.origen_variable if loc else None,
                "Data Mapeo":         str(m.created_at)[:10] if m.created_at else None,
                "Validat":            "Sí" if m.validado else "No",
            })

        df = pd.DataFrame(rows)
        buf = io.BytesIO()
        sheet = "Selecció Tots Centres" if ref_ids else "Tots els Mapeos"
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet, index=False)
        buf.seek(0)
        return buf.getvalue()
