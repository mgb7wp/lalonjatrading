"""registro de experimentos de backtest

Tabla `backtest_run`: una fila por experimento DISTINTO, no por ejecucion. La
restriccion UNIQUE sobre `fingerprint` es lo que hace que contar filas cuente
experimentos, que es la cifra con la que se juzga el riesgo de sobreajuste
(RT-1 del plan). Ver `backend/db/experimentos.py`.

Revision ID: 348a52a5d33d
Revises: 478a967bccd7
Create Date: 2026-09-16 10:12:46.780230
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "348a52a5d33d"
down_revision: str | None = "478a967bccd7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_version_id", sa.Integer(), nullable=False),
        sa.Column("period_kind", sa.String(length=16), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("data_source", sa.String(length=32), nullable=False),
        sa.Column("universe_hash", sa.String(length=64), nullable=False, comment="sha256"),
        sa.Column("universe_size", sa.Integer(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, comment="sha256"),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "period_kind IN ('diseno', 'validacion', 'completo')",
            name=op.f("ck_backtest_run_period_kind_valido"),
        ),
        sa.CheckConstraint(
            "period_end > period_start", name=op.f("ck_backtest_run_periodo_no_vacio")
        ),
        sa.CheckConstraint("run_count > 0", name=op.f("ck_backtest_run_run_count_positivo")),
        sa.CheckConstraint("universe_size > 0", name=op.f("ck_backtest_run_universo_no_vacio")),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_version.id"],
            name=op.f("fk_backtest_run_model_version_id_model_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_run")),
        sa.UniqueConstraint("fingerprint", name="uq_backtest_run_fingerprint"),
    )
    op.create_index(
        "ix_backtest_run_period_kind_created_at",
        "backtest_run",
        ["period_kind", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_run_period_kind_created_at", table_name="backtest_run")
    op.drop_table("backtest_run")
