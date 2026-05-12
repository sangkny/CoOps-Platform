"""SaaS billing ORM — shared.make_billing_models 로 ``coops_`` prefix 적용."""
from __future__ import annotations

from database import Base
from saas import make_billing_models

(
    BillingPlan,
    BillingSubscription,
    BillingUsageRecord,
    BillingMonthlyUserUsage,
) = make_billing_models(Base, table_prefix="coops_")

__all__ = [
    "BillingPlan",
    "BillingSubscription",
    "BillingUsageRecord",
    "BillingMonthlyUserUsage",
]
