"""cop005 — Stripe sidecar 테이블 2종 for CoOps (B-7, 2026-05-12).

기존 ``coops_billing_plans`` / ``coops_billing_subscriptions`` 무변경 — sidecar:
    - ``coops_stripe_plan_mappings``
    - ``coops_stripe_subscriptions``
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cop005_stripe_sidecar"
down_revision: Union[str, None] = "cop004_content_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coops_stripe_plan_mappings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("stripe_price_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["coops_billing_plans.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_id", name="uq_coops_stripe_plan_mappings_plan_id"
        ),
        sa.UniqueConstraint(
            "stripe_price_id",
            name="uq_coops_stripe_plan_mappings_stripe_price_id",
        ),
    )
    op.create_index(
        "ix_coops_stripe_plan_mappings_plan_id",
        "coops_stripe_plan_mappings", ["plan_id"],
    )
    op.create_index(
        "ix_coops_stripe_plan_mappings_stripe_price_id",
        "coops_stripe_plan_mappings", ["stripe_price_id"],
    )

    op.create_table(
        "coops_stripe_subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), nullable=False),
        sa.Column(
            "stripe_customer_id", sa.String(length=128), nullable=False
        ),
        sa.Column(
            "stripe_subscription_id", sa.String(length=128), nullable=False
        ),
        sa.Column(
            "stripe_status", sa.String(length=32), nullable=False,
            server_default="incomplete",
        ),
        sa.Column(
            "current_period_end", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "cancel_at_period_end", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["coops_billing_subscriptions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subscription_id",
            name="uq_coops_stripe_subscriptions_subscription_id",
        ),
        sa.UniqueConstraint(
            "stripe_subscription_id",
            name="uq_coops_stripe_subscriptions_stripe_subscription_id",
        ),
    )
    op.create_index(
        "ix_coops_stripe_subscriptions_subscription_id",
        "coops_stripe_subscriptions", ["subscription_id"],
    )
    op.create_index(
        "ix_coops_stripe_subscriptions_stripe_customer_id",
        "coops_stripe_subscriptions", ["stripe_customer_id"],
    )
    op.create_index(
        "ix_coops_stripe_subscriptions_stripe_subscription_id",
        "coops_stripe_subscriptions", ["stripe_subscription_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_coops_stripe_subscriptions_stripe_subscription_id",
        table_name="coops_stripe_subscriptions",
    )
    op.drop_index(
        "ix_coops_stripe_subscriptions_stripe_customer_id",
        table_name="coops_stripe_subscriptions",
    )
    op.drop_index(
        "ix_coops_stripe_subscriptions_subscription_id",
        table_name="coops_stripe_subscriptions",
    )
    op.drop_table("coops_stripe_subscriptions")
    op.drop_index(
        "ix_coops_stripe_plan_mappings_stripe_price_id",
        table_name="coops_stripe_plan_mappings",
    )
    op.drop_index(
        "ix_coops_stripe_plan_mappings_plan_id",
        table_name="coops_stripe_plan_mappings",
    )
    op.drop_table("coops_stripe_plan_mappings")
