"""cop006 — Push devices 테이블 for CoOps (E-Day 4, 2026-05-13).

`coops_push_devices` 단일 테이블 — Expo push token 단위로 row 1.
soft delete 컬럼 (active, revoked_at). user_id index + token unique.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cop006_push_devices"
down_revision: Union[str, None] = "cop005_stripe_sidecar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coops_push_devices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=128), nullable=False, index=True),
        sa.Column(
            "expo_push_token",
            sa.String(length=256),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("platform", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("device_label", sa.String(length=128), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("coops_push_devices")
