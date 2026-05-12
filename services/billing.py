"""CoOps 의 SaaS BillingService 인스턴스 + 함수형 API thin wrapper.

shared.BillingService 를 ``coops_billing_*`` 테이블에 매핑된 ORM 으로 초기화.
api/billing.py 가 이 인스턴스/함수들을 import 해 사용.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.billing import (
    BillingMonthlyUserUsage,
    BillingPlan,
    BillingSubscription,
    BillingUsageRecord,
    StripePlanMapping,
    StripeSubscription,
)
from saas import BillingService, StripeConfig, StripeService
from saas.helpers import (
    DEFAULT_FREE_PLAN_CODE,
    current_year_month,
    parse_allowed_models,
    usage_snapshot_dict,
)

coops_billing = BillingService(
    plan_cls=BillingPlan,
    subscription_cls=BillingSubscription,
    usage_record_cls=BillingUsageRecord,
    monthly_usage_cls=BillingMonthlyUserUsage,
    default_free_code=DEFAULT_FREE_PLAN_CODE,
    service_name="coops",
)

# Stripe 어댑터 — env 토글 (``COOPS_STRIPE_ENABLED`` 또는 ``STRIPE_ENABLED``).
coops_stripe_config = StripeConfig.from_env(prefix="COOPS_")
coops_stripe = StripeService(
    config=coops_stripe_config,
    billing=coops_billing,
    plan_mapping_cls=StripePlanMapping,
    stripe_subscription_cls=StripeSubscription,
)


async def get_plan_by_code(db: AsyncSession, code: str):
    return await coops_billing.get_plan_by_code(db, code)


async def list_active_plans(db: AsyncSession) -> list[Any]:
    return await coops_billing.list_active_plans(db)


async def get_active_subscription(db: AsyncSession, user_id: str):
    return await coops_billing.get_active_subscription(db, user_id)


async def get_or_create_active_subscription(
    db: AsyncSession, user_id: str
) -> tuple[Any, Any]:
    return await coops_billing.get_or_create_active_subscription(db, user_id)


async def switch_subscription(
    db: AsyncSession, user_id: str, new_plan_code: str
) -> tuple[Any, Any, str | None]:
    return await coops_billing.switch_subscription(db, user_id, new_plan_code)


async def get_or_create_monthly_usage(
    db: AsyncSession, user_id: str, *, year_month: str | None = None
):
    return await coops_billing.get_or_create_monthly_usage(
        db, user_id, year_month=year_month
    )


__all__ = [
    "DEFAULT_FREE_PLAN_CODE",
    "coops_billing",
    "coops_stripe",
    "coops_stripe_config",
    "current_year_month",
    "get_plan_by_code",
    "list_active_plans",
    "get_active_subscription",
    "get_or_create_active_subscription",
    "switch_subscription",
    "get_or_create_monthly_usage",
    "parse_allowed_models",
    "usage_snapshot_dict",
]
