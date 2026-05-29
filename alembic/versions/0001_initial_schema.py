"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Sistema ───────────────────────────────────────────────────────────────
    op.create_table(
        "Sistema",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sistema", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_Sistema_id", "Sistema", ["id"])
    op.create_index("ix_Sistema_sistema", "Sistema", ["sistema"], unique=True)

    # ── Hospital ──────────────────────────────────────────────────────────────
    op.create_table(
        "Hospital",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hospital", sa.String(), nullable=False),
        sa.Column("acronim", sa.String(), nullable=False),
        sa.Column("codi", sa.String(), nullable=False),
        sa.Column("system_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["system_id"], ["Sistema.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_Hospital_id", "Hospital", ["id"])
    op.create_index("ix_Hospital_hospital", "Hospital", ["hospital"], unique=True)
    op.create_index("ix_Hospital_acronim", "Hospital", ["acronim"], unique=True)
    op.create_index("ix_Hospital_codi", "Hospital", ["codi"], unique=True)
    op.create_index("ix_Hospital_system_id", "Hospital", ["system_id"])

    # ── User ──────────────────────────────────────────────────────────────────
    op.create_table(
        "User",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("rol", sa.String(), nullable=False),
        sa.Column("hospital_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["hospital_id"], ["Hospital.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_User_id", "User", ["id"])
    op.create_index("ix_User_username", "User", ["username"], unique=True)
    op.create_index("ix_User_email", "User", ["email"], unique=True)
    op.create_index("ix_User_hospital_id", "User", ["hospital_id"])

    # ── PasswordResetToken ────────────────────────────────────────────────────
    op.create_table(
        "PasswordResetToken",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["User.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_PasswordResetToken_id", "PasswordResetToken", ["id"])
    op.create_index("ix_PasswordResetToken_user_id", "PasswordResetToken", ["user_id"])

    # ── VarsLocal ─────────────────────────────────────────────────────────────
    op.create_table(
        "VarsLocal",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("variable_id", sa.Integer(), nullable=True),
        sa.Column("value", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("tipo_variable", sa.String(), nullable=True),
        sa.Column("origen_variable", sa.String(), nullable=True),
        sa.Column("clave", sa.String(), nullable=True),
        sa.Column("last_value", sa.Date(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("q1", sa.Float(), nullable=True),
        sa.Column("q2", sa.Float(), nullable=True),
        sa.Column("q3", sa.Float(), nullable=True),
        sa.Column("porc_pats", sa.Float(), nullable=True),
        sa.Column("cadencia", sa.String(), nullable=True),
        sa.Column("codigo", sa.String(), nullable=True),
        sa.Column("tabla_origen", sa.String(), nullable=True),
        sa.Column("hospital_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["hospital_id"], ["Hospital.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("variable_id", "value", "tabla_origen", "hospital_id", name="uq_local_var"),
    )
    op.create_index("ix_VarsLocal_id", "VarsLocal", ["id"])
    op.create_index("ix_VarsLocal_variable_id", "VarsLocal", ["variable_id"])
    op.create_index("ix_VarsLocal_hospital_id", "VarsLocal", ["hospital_id"])

    # ── VarsRef ───────────────────────────────────────────────────────────────
    op.create_table(
        "VarsRef",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("variable", sa.String(), nullable=False),
        sa.Column("grupo", sa.String(), nullable=True),
        sa.Column("tipo_variable", sa.String(), nullable=True),
        sa.Column("descripcion_socmic", sa.Text(), nullable=True),
        sa.Column("snomed_id", sa.String(), nullable=True),
        sa.Column("snomed_term", sa.String(), nullable=True),
        sa.Column("snomed_categoria", sa.String(), nullable=True),
        sa.Column("icd10_code", sa.String(), nullable=True),
        sa.Column("snomed_origen_mapeo", sa.String(), nullable=True),
        sa.Column("snomed_score", sa.Float(), nullable=True),
        sa.Column("arquetipo_id", sa.String(), nullable=True),
        sa.Column("at_code", sa.String(), nullable=True),
        sa.Column("openehr_nombre", sa.String(), nullable=True),
        sa.Column("openehr_descripcion", sa.Text(), nullable=True),
        sa.Column("openehr_tipo_dato", sa.String(), nullable=True),
        sa.Column("openehr_categoria", sa.String(), nullable=True),
        sa.Column("openehr_tipo_var", sa.String(), nullable=True),
        sa.Column("unidad_ucum", sa.String(), nullable=True),
        sa.Column("unidad_openehr", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_VarsRef_id", "VarsRef", ["id"])
    op.create_index("ix_VarsRef_variable", "VarsRef", ["variable"], unique=True)
    op.create_index("ix_VarsRef_snomed_id", "VarsRef", ["snomed_id"])

    # ── VarsMapped ────────────────────────────────────────────────────────────
    op.create_table(
        "VarsMapped",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("local_pk", sa.Integer(), nullable=False),
        sa.Column("ref_pk", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("validado", sa.Boolean(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("notas_validacion", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["local_pk"], ["VarsLocal.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ref_pk"], ["VarsRef.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["User.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_VarsMapped_id", "VarsMapped", ["id"])
    op.create_index("ix_VarsMapped_local_pk", "VarsMapped", ["local_pk"])
    op.create_index("ix_VarsMapped_ref_pk", "VarsMapped", ["ref_pk"])
    op.create_index("ix_VarsMapped_user_id", "VarsMapped", ["user_id"])


def downgrade() -> None:
    op.drop_table("VarsMapped")
    op.drop_table("VarsRef")
    op.drop_table("VarsLocal")
    op.drop_table("PasswordResetToken")
    op.drop_table("User")
    op.drop_table("Hospital")
    op.drop_table("Sistema")
