"""CoOps 의 Quota Enforcement + record_call (shared.saas.quota 위임)."""
from __future__ import annotations

from auth.dependencies import current_user_strict
from database import get_db
from saas import QuotaContext, make_enforce_quota_dep, quota_headers
from saas import record_call as _shared_record_call
from services.billing import coops_billing

enforce_quota = make_enforce_quota_dep(
    coops_billing,
    get_user=current_user_strict,
    get_db=get_db,
)


async def record_call(
    db,
    quota: QuotaContext,
    *,
    success: bool,
    model_used: str | None = None,
    tokens_estimated: int = 0,
    latency_ms: int | None = None,
) -> None:
    return await _shared_record_call(
        coops_billing,
        db,
        quota,
        success=success,
        model_used=model_used,
        tokens_estimated=tokens_estimated,
        latency_ms=latency_ms,
    )


__all__ = [
    "QuotaContext",
    "enforce_quota",
    "quota_headers",
    "record_call",
]
