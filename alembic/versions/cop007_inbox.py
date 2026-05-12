"""cop007 — In-app Notification inbox 테이블 (E-R2-Day 1, 2026-05-13).

`coops_notifications` 단일 테이블 — push 발송과 별개로 *서버에 영속화* 되는 알림.
mobile 의 `/notifications/inbox` 가 이 row 들을 read. 읽음 처리 PATCH 지원.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cop007_inbox"
down_revision: Union[str, None] = "cop006_push_devices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coops_notifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=128), nullable=False, index=True),
        sa.Column("kind", sa.String(length=48), nullable=False, index=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("ref_id", sa.String(length=64), nullable=True),
        sa.Column("data_json", sa.Text(), nullable=True),
        sa.Column(
            "read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            index=True,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_coops_notifications_user_created",
        "coops_notifications",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_coops_notifications_user_created", table_name="coops_notifications")
    op.drop_table("coops_notifications")
