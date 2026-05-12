"""cop008 — Stripe sidecar v2 컬럼 (B-7 Round 2, 2026-05-13).

``coops_stripe_subscriptions`` 에 invoice/refund 메타 컬럼 3개 추가.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cop008_stripe_r2"
down_revision: Union[str, None] = "cop007_inbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "coops_stripe_subscriptions",
        sa.Column("last_paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "coops_stripe_subscriptions",
        sa.Column("last_paid_amount_cents", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "coops_stripe_subscriptions",
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("coops_stripe_subscriptions", "last_failure_at")
    op.drop_column("coops_stripe_subscriptions", "last_paid_amount_cents")
    op.drop_column("coops_stripe_subscriptions", "last_paid_at")
