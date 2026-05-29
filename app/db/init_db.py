"""
Seed inicial de la base de datos:
  1. Instala extensión unaccent de PostgreSQL (idempotente)
  2. Seed: sistemas, hospitales y usuario admin

Las tablas las crea Alembic (alembic upgrade head) antes de llamar a este script.
"""
import logging

from sqlalchemy import text

from app.db.database import engine, SessionLocal
from app.db.models import Hospital, Sistema, User
from app.db.security import hash_password

logger = logging.getLogger(__name__)

# ─── Datos semilla ───────────────────────────────────────────────────────────

_SISTEMAS = [
    {"sistema": "CCC"},
    {"sistema": "CHA"},
]

_HOSPITALES = [
    {"sistema": "CCC", "hospital": "Hospital Universitari Joan XXIII de Tarragona", "acronim": "JX",   "codi": "39"},
    {"sistema": "CCC", "hospital": "Hospital de Tortosa Verge de la Cinta",          "acronim": "VC",   "codi": "86"},
    {"sistema": "CCC", "hospital": "Hospital Universitari Germans Trias i Pujol",    "acronim": "GT",   "codi": "272"},
    {"sistema": "CCC", "hospital": "Hospital Universitari Arnau de Vilanova",        "acronim": "AR",   "codi": "1"},
    {"sistema": "CCC", "hospital": "Hospital Universitari Vall d'Hebron",            "acronim": "VH",   "codi": "6046"},
    {"sistema": "CHA", "hospital": "Hospital Universitari de Girona Doctor J. Trueta","acronim": "DT",  "codi": "100"},
    {"sistema": "CCC", "hospital": "Hospital Universitari de Bellvitge",             "acronim": "BLL",  "codi": "148"},
    {"sistema": "CCC", "hospital": "Hospital Universitari de Vic",                   "acronim": "VIC",  "codi": "745"},
    {"sistema": "CCC", "hospital": "Hospital Sant Joan de Reus",                     "acronim": "SJR",  "codi": "763"},
    {"sistema": "CCC", "hospital": "Pius Hospital de Valls",                         "acronim": "PV",   "codi": "826"},
    {"sistema": "CCC", "hospital": "Hospital de Palamós",                            "acronim": "PLM",  "codi": "739"},
    {"sistema": "CCC", "hospital": "Hospital Sant Pau i Santa Tecla",               "acronim": "SPST", "codi": "767"},
    {"sistema": "CCC", "hospital": "Centre MQ Reus",                                "acronim": "CMQ",  "codi": "1346"},
    {"sistema": "CCC", "hospital": "Hospital del Vendrell",                          "acronim": "HVN",  "codi": "4373"},
    {"sistema": "CCC", "hospital": "Hospital Comarcal d'Amposta",                   "acronim": "HCA",  "codi": "975"},
    {"sistema": "CCC", "hospital": "Fundació Salut Empordà - Hospital de Figueres", "acronim": "FSE",  "codi": "724"},
    {"sistema": "CCC", "hospital": "Hospital Comarcal Móra d'Ebre",                 "acronim": "HME",  "codi": "737"},
    {"sistema": "CCC", "hospital": "Hosp. d'Olot i Comarcal de la Garrotxa",        "acronim": "HOG",  "codi": "762"},
    {"sistema": "CCC", "hospital": "Hospital Santa Caterina",                       "acronim": "HSC",  "codi": "770"},
    {"sistema": "CCC", "hospital": "Hospital Comarcal de Blanes",                   "acronim": "HCB",  "codi": "719"},
]

# Un admin por hospital con password temporal "Admin123!" (debe cambiarse)
_DEFAULT_ADMIN_PASSWORD = "Admin123!"

_SUPERADMIN = {
    "username": "superadmin",
    "email":    "superadmin@eina-mapeig.cat",
    # hospital_id és obligatori al model; el superadmin bypassa el filtre per rol="superadmin"
    "hospital_acronim": "JX",
}
_DEFAULT_SUPERADMIN_PASSWORD = "Superadmin123!"


# ─── Función principal ────────────────────────────────────────────────────────

def init_db():
    # 1. Extensión unaccent (necesaria para búsquedas sin acentos)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent;"))
    logger.info("Extensió 'unaccent' activa.")

    # 2. Seed
    with SessionLocal() as db:
        _seed_sistemas(db)
        _seed_hospitales(db)
        _seed_admins(db)
        _seed_superadmin(db)
        db.commit()

    logger.info("Base de dades inicialitzada.")


def _seed_sistemas(db):
    for s in _SISTEMAS:
        if not db.query(Sistema).filter(Sistema.sistema == s["sistema"]).first():
            db.add(Sistema(sistema=s["sistema"]))
            logger.info(f"Sistema creat: {s['sistema']}")
    db.flush()


def _seed_hospitales(db):
    for h in _HOSPITALES:
        if db.query(Hospital).filter(Hospital.codi == h["codi"]).first():
            continue
        sistema = db.query(Sistema).filter(Sistema.sistema == h["sistema"]).first()
        if not sistema:
            logger.warning(f"Sistema '{h['sistema']}' no trobat per a {h['acronim']}, saltant.")
            continue
        db.add(Hospital(
            hospital=h["hospital"],
            acronim=h["acronim"],
            codi=h["codi"],
            system_id=sistema.id
        ))
        logger.info(f"Hospital creat: {h['acronim']}")
    db.flush()


def _seed_admins(db):
    password_hash = hash_password(_DEFAULT_ADMIN_PASSWORD)
    for h in _HOSPITALES:
        hospital = db.query(Hospital).filter(Hospital.codi == h["codi"]).first()
        if not hospital:
            continue
        email = f"admin@{h['acronim'].lower()}.cat"
        username = f"admin_{h['acronim'].lower()}"
        if not db.query(User).filter(User.email == email).first():
            db.add(User(
                username=username,
                email=email,
                password_hash=password_hash,
                rol="admin",
                hospital_id=hospital.id
            ))
            logger.info(f"Admin creat: {email} (password temporal: {_DEFAULT_ADMIN_PASSWORD})")
    db.flush()


def _seed_superadmin(db):
    if db.query(User).filter(User.username == _SUPERADMIN["username"]).first():
        return
    hospital = db.query(Hospital).filter(Hospital.acronim == _SUPERADMIN["hospital_acronim"]).first()
    if not hospital:
        logger.warning("No s'ha trobat el hospital per al superadmin, saltant.")
        return
    db.add(User(
        username=_SUPERADMIN["username"],
        email=_SUPERADMIN["email"],
        password_hash=hash_password(_DEFAULT_SUPERADMIN_PASSWORD),
        rol="superadmin",
        hospital_id=hospital.id
    ))
    logger.info(f"Superadmin creat: {_SUPERADMIN['email']} (password temporal: {_DEFAULT_SUPERADMIN_PASSWORD})")
    db.flush()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
