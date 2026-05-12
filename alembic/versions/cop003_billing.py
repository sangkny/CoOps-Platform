"""cop003 — SaaS billing (CoOps 가격 모델, Phase 2 → C-4).

shared-libraries 의 ``make_billing_models`` 가 생성하는 4개 ORM (테이블 prefix
``coops_``) 와 동일 스키마. 한장요약 §"CoOps 가격 모델" 의 3-tier ($199/$499/$999)
+ Free (월 50회 트라이얼) 를 시드한다.

Upgrade: ``coops_billing_*`` 4테이블 + Plan 4종.
Downgrade: 4테이블 모두 drop.
"""
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cop003_billing"
down_revision: Union[str, None] = "cop002_contract_analysis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coops_billing_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "price_usd_per_month", sa.Numeric(10, 2), nullable=False, server_default="0"
        ),
        sa.Column("monthly_call_quota", sa.Integer(), nullable=True),
        sa.Column(
            "allowed_models", sa.String(length=128), nullable=False, server_default="FAST"
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_coops_billing_plans_code"),
    )
    op.create_index(
        "ix_coops_billing_plans_code", "coops_billing_plans", ["code"], unique=True
    )

    op.create_table(
        "coops_billing_subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="active"
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["coops_billing_plans.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_coops_billing_subscriptions_user_id",
        "coops_billing_subscriptions",
        ["user_id"],
    )
    op.create_index(
        "ix_coops_billing_subscriptions_status",
        "coops_billing_subscriptions",
        ["status"],
    )

    op.create_table(
        "coops_billing_usage_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("plan_code", sa.String(length=32), nullable=False),
        sa.Column(
            "tokens_estimated", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("model_used", sa.String(length=128), nullable=True),
        sa.Column(
            "success", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_coops_billing_usage_records_user_id",
        "coops_billing_usage_records",
        ["user_id"],
    )
    op.create_index(
        "ix_coops_billing_usage_records_action",
        "coops_billing_usage_records",
        ["action"],
    )
    op.create_index(
        "ix_coops_billing_usage_records_created_at",
        "coops_billing_usage_records",
        ["created_at"],
    )

    op.create_table(
        "coops_billing_monthly_user_usage",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("year_month", sa.String(length=7), nullable=False),
        sa.Column(
            "calls_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "tokens_total", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("cost_usd", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "year_month",
            name="uq_coops_billing_monthly_user_year_month",
        ),
    )
    op.create_index(
        "ix_coops_billing_monthly_user_usage_user_id",
        "coops_billing_monthly_user_usage",
        ["user_id"],
    )
    op.create_index(
        "ix_coops_billing_monthly_user_usage_year_month",
        "coops_billing_monthly_user_usage",
        ["year_month"],
    )

    # Plan 4종 시드 — 한장요약 §"CoOps 가격 모델"
    # Free 50회/월 트라이얼 + Startup $199 / SMB $499 / Ent $999.
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    seed_plans = [
        {
            "id": "coops-plan-free",
            "code": "free",
            "name": "Free",
            "price_usd_per_month": 0,
            "monthly_call_quota": 50,
            "allowed_models": "FAST",
            "description": (
                "30일 무료 트라이얼 — 결재 50회/월, FAST 모델. 베타 고객 무상 제공 (10명 한정)."
            ),
        },
        {
            "id": "coops-plan-startup",
            "code": "startup",
            "name": "Startup",
            "price_usd_per_month": 199,
            "monthly_call_quota": 500,
            "allowed_models": "FAST",
            "description": (
                "스타트업 (1~10명) — 결재 500회/월, FAST 모델, 기본 BUSINESS Ontology 검증."
            ),
        },
        {
            "id": "coops-plan-smb",
            "code": "smb",
            "name": "SMB",
            "price_usd_per_month": 499,
            "monthly_call_quota": 5000,
            "allowed_models": "FAST,HEAVY",
            "description": (
                "중소기업 (10~50명) — 결재+보고서+광고영상+투자자미팅+KPI+캘린더, "
                "월 5,000회, FAST+HEAVY 모델."
            ),
        },
        {
            "id": "coops-plan-ent",
            "code": "ent",
            "name": "Enterprise",
            "price_usd_per_month": 999,
            "monthly_call_quota": None,
            "allowed_models": "FAST,HEAVY,CONSENSUS",
            "description": (
                "엔터프라이즈 (50명 이상) — 멀티 회사, SSO/SLA, 무제한, 전체 모델 (CONSENSUS 포함)."
            ),
        },
    ]
    for p in seed_plans:
        bind.execute(
            sa.text(
                "INSERT INTO coops_billing_plans "
                "(id, code, name, price_usd_per_month, monthly_call_quota, "
                " allowed_models, description, is_active, created_at, updated_at) "
                "VALUES (:id, :code, :name, :price, :quota, :models, :desc, "
                "        true, :now, :now)"
            ),
            {
                "id": p["id"],
                "code": p["code"],
                "name": p["name"],
                "price": p["price_usd_per_month"],
                "quota": p["monthly_call_quota"],
                "models": p["allowed_models"],
                "desc": p["description"],
                "now": now,
            },
        )


def downgrade() -> None:
    op.drop_index(
        "ix_coops_billing_monthly_user_usage_year_month",
        table_name="coops_billing_monthly_user_usage",
    )
    op.drop_index(
        "ix_coops_billing_monthly_user_usage_user_id",
        table_name="coops_billing_monthly_user_usage",
    )
    op.drop_table("coops_billing_monthly_user_usage")

    op.drop_index(
        "ix_coops_billing_usage_records_created_at",
        table_name="coops_billing_usage_records",
    )
    op.drop_index(
        "ix_coops_billing_usage_records_action",
        table_name="coops_billing_usage_records",
    )
    op.drop_index(
        "ix_coops_billing_usage_records_user_id",
        table_name="coops_billing_usage_records",
    )
    op.drop_table("coops_billing_usage_records")

    op.drop_index(
        "ix_coops_billing_subscriptions_status",
        table_name="coops_billing_subscriptions",
    )
    op.drop_index(
        "ix_coops_billing_subscriptions_user_id",
        table_name="coops_billing_subscriptions",
    )
    op.drop_table("coops_billing_subscriptions")

    op.drop_index("ix_coops_billing_plans_code", table_name="coops_billing_plans")
    op.drop_table("coops_billing_plans")
