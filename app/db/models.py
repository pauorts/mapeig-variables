from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    Date, DateTime, Text, ForeignKey, UniqueConstraint, func
)
from sqlalchemy.orm import relationship

from .database import Base



# ═══════════════════════════════════════════════════════════════════════════════
# SISTEMAS
# ═══════════════════════════════════════════════════════════════════════════════

class Sistema(Base):
    __tablename__ = "Sistema"

    id      = Column(Integer, primary_key=True, index=True)
    sistema = Column(String, unique=True, index=True, nullable=False)

    hospitales = relationship(
        "Hospital",
        back_populates="system",
        cascade="all, delete-orphan"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# HOSPITALES
# ═══════════════════════════════════════════════════════════════════════════════

class Hospital(Base):
    __tablename__ = "Hospital"

    id        = Column(Integer, primary_key=True, index=True)
    hospital  = Column(String, unique=True, index=True, nullable=False)
    acronim   = Column(String, unique=True, index=True, nullable=False)
    codi      = Column(String, unique=True, index=True, nullable=False)
    system_id = Column(
        Integer,
        ForeignKey("Sistema.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    system    = relationship("Sistema", back_populates="hospitales")
    usuarios  = relationship("User", back_populates="hospital", cascade="all, delete-orphan")
    variables = relationship("VarsLocal", back_populates="hospital", cascade="all, delete-orphan")


# ═══════════════════════════════════════════════════════════════════════════════
# USUARIOS
# ═══════════════════════════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "User"

    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String, unique=True, index=True, nullable=False)
    email         = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    rol           = Column(String, nullable=False)
    hospital_id   = Column(
        Integer,
        ForeignKey("Hospital.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    hospital     = relationship("Hospital", back_populates="usuarios")
    mappings     = relationship("VarsMapped", back_populates="user", cascade="all, delete-orphan")
    reset_tokens = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")


# ═══════════════════════════════════════════════════════════════════════════════
# TOKENS RESET CONTRASEÑA / INVITACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

class PasswordResetToken(Base):
    __tablename__ = "PasswordResetToken"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("User.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at    = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="reset_tokens")


# ═══════════════════════════════════════════════════════════════════════════════
# VARIABLES LOCALES DEL HOSPITAL
# ═══════════════════════════════════════════════════════════════════════════════

class VarsLocal(Base):
    """
    Variables locales extraídas del SIC de cada hospital.
    Cada fila = una variable tal como existe en los sistemas del hospital,
    antes de ser mapeada al catálogo de referencia SOCMIC.
    """
    __tablename__ = "VarsLocal"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    variable_id     = Column(Integer, index=True, nullable=True)
    value           = Column(Integer, nullable=True)
    description     = Column(String, nullable=True)
    tipo_variable   = Column(String, nullable=True)
    origen_variable = Column(String, nullable=True)
    clave           = Column(String, nullable=True)
    last_value      = Column(Date, nullable=True)
    count           = Column(Integer, default=0)
    q1              = Column(Float, nullable=True)
    q2              = Column(Float, nullable=True)
    q3              = Column(Float, nullable=True)
    porc_pats       = Column(Float, default=0)
    cadencia        = Column(String, nullable=True)
    codigo          = Column(String, nullable=True)
    tabla_origen    = Column(String, nullable=True)
    hospital_id     = Column(
        Integer,
        ForeignKey("Hospital.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    hospital = relationship("Hospital", back_populates="variables")
    mappings = relationship("VarsMapped", back_populates="local_variable", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('variable_id', 'value', 'tabla_origen', 'hospital_id', name='uq_local_var'),
    )

    def __repr__(self):
        return f"<VarsLocal(id={self.id}, description={self.description})>"


# ═══════════════════════════════════════════════════════════════════════════════
# CATÁLOGO DE REFERENCIA UCI (SOCMIC + openEHR + SNOMED)
# ═══════════════════════════════════════════════════════════════════════════════

class VarsRef(Base):
    """
    Tabla maestra de variables UCI de referencia para Cataluña.
    Cada fila = una variable clínica consensuada por SOCMIC, enriquecida
    con su estructura openEHR y su identificador SNOMED canónico.
    """
    __tablename__ = "VarsRef"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── IDENTIDAD PRINCIPAL (fuente: Excel SOCMIC) ────────────────────────────
    variable           = Column(String, nullable=False, unique=True, index=True)
    grupo              = Column(String, nullable=True)
    tipo_variable      = Column(String, nullable=True)
    descripcion_socmic = Column(Text, nullable=True)

    # ── ENLACE SNOMED CT ──────────────────────────────────────────────────────
    snomed_id           = Column(String, nullable=True, index=True)
    snomed_term         = Column(String, nullable=True)
    snomed_categoria    = Column(String, nullable=True)
    icd10_code          = Column(String, nullable=True)
    snomed_origen_mapeo = Column(String, nullable=True)
    snomed_score        = Column(Float, nullable=True)

    # ── ESTRUCTURA openEHR ────────────────────────────────────────────────────
    arquetipo_id        = Column(String, nullable=True)
    at_code             = Column(String, nullable=True)
    openehr_nombre      = Column(String, nullable=True)
    openehr_descripcion = Column(Text, nullable=True)
    openehr_tipo_dato   = Column(String, nullable=True)
    openehr_categoria   = Column(String, nullable=True)
    openehr_tipo_var    = Column(String, nullable=True)

    # ── UNIDADES ──────────────────────────────────────────────────────────────
    unidad_ucum    = Column(String, nullable=True)
    unidad_openehr = Column(String, nullable=True)

    mappings = relationship(
        "VarsMapped",
        back_populates="variable_referencia",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<VarsRef(id={self.id}, variable='{self.variable}', snomed_id={self.snomed_id})>"


# ═══════════════════════════════════════════════════════════════════════════════
# MAPEOS: variable local hospital ↔ variable de referencia
# ═══════════════════════════════════════════════════════════════════════════════

class VarsMapped(Base):
    """
    Mapeo entre una variable local del hospital (VarsLocal)
    y una variable del catálogo de referencia (VarsRef).
    Los datos de la variable (q1-q3, tipo, snomed, etc.) se leen
    directamente desde VarsLocal y VarsRef vía las FK.
    """
    __tablename__ = "VarsMapped"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── CLAVES FORÁNEAS ───────────────────────────────────────────────────────
    local_pk = Column(Integer, ForeignKey("VarsLocal.id", ondelete="CASCADE"), nullable=False, index=True)
    ref_pk   = Column(Integer, ForeignKey("VarsRef.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id  = Column(Integer, ForeignKey("User.id", ondelete="CASCADE"), nullable=False, index=True)

    # ── GOBERNANZA Y VALIDACIÓN ───────────────────────────────────────────────
    validado         = Column(Boolean, default=False, nullable=False)
    activo           = Column(Boolean, default=True, nullable=False)
    notas_validacion = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # ── RELACIONES ────────────────────────────────────────────────────────────
    local_variable      = relationship("VarsLocal", back_populates="mappings")
    variable_referencia = relationship("VarsRef", back_populates="mappings")
    user                = relationship("User", back_populates="mappings")

    def __repr__(self):
        return f"<VarsMapped(id={self.id}, local_pk={self.local_pk}, ref_pk={self.ref_pk})>"
