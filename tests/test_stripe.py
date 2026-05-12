"""B-7: CoOps Stripe 결제 게이트웨이 통합 테스트.

ADK 의 ``tests/test_stripe.py`` 와 동일 패턴. CoOps 의 plan 시드 (free/startup/smb/ent)
에서 ``startup`` 을 paid plan 으로 사용.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from database import async_session_maker
from models import (
    BillingPlan,
    BillingSubscription,
    StripePlanMapping,
    StripeSubscription,
)
from saas.stripe_service import StripeConfig
from services.billing import coops_stripe


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "admin123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _staff_headers(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token",
        data={"username": "staff", "password": "staff123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@contextmanager
def _stripe_enabled(*, skip_sig: bool = True):
    original = coops_stripe.config
    coops_stripe.config = StripeConfig(
        enabled=True,
        secret_key="sk_test_dummy",
        webhook_secret="whsec_test_dummy",
        public_key="pk_test_dummy",
        skip_signature_verification=skip_sig,
    )
    try:
        yield
    finally:
        coops_stripe.config = original


async def _ensure_paid_plan_mapping() -> tuple[str, str]:
    plan_code = "startup"
    price_id = f"price_test_{uuid.uuid4().hex[:12]}"
    async with async_session_maker() as s:
        plan = await s.scalar(
            select(BillingPlan).where(BillingPlan.code == plan_code)
        )
        assert plan is not None, "alembic cop003_billing 시드 (startup plan) 누락"
        existing = await s.scalar(
            select(StripePlanMapping).where(StripePlanMapping.plan_id == plan.id)
        )
        if existing is not None:
            existing.stripe_price_id = price_id
        else:
            s.add(StripePlanMapping(
                id=str(uuid.uuid4()),
                plan_id=plan.id,
                stripe_price_id=price_id,
            ))
        await s.commit()
    return plan_code, price_id


# ── 1. /status ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stripe_status_default_disabled(client: AsyncClient) -> None:
    r = await client.get("/api/v1/billing/stripe/status")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_stripe_status_enabled_shows_public_key(
    client: AsyncClient,
) -> None:
    with _stripe_enabled():
        r = await client.get("/api/v1/billing/stripe/status")
    body = r.json()
    assert body["enabled"] is True
    assert body["public_key"] == "pk_test_dummy"


# ── 2. /checkout ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_checkout_no_auth_returns_401(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/billing/stripe/checkout", json={"plan_code": "startup"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_checkout_disabled_returns_503(client: AsyncClient) -> None:
    hdr = await _staff_headers(client)
    r = await client.post(
        "/api/v1/billing/stripe/checkout",
        json={"plan_code": "startup"},
        headers=hdr,
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_checkout_unknown_plan_returns_400(client: AsyncClient) -> None:
    hdr = await _staff_headers(client)
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/checkout",
            json={"plan_code": "_no_such_"},
            headers=hdr,
        )
    assert r.status_code == 400


# ── 3. /webhook ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_disabled_returns_503(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/billing/stripe/webhook",
        content=b"{}",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_webhook_invalid_json_returns_400(client: AsyncClient) -> None:
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_webhook_unsupported_event_returns_ignored(
    client: AsyncClient,
) -> None:
    """R2 부터 invoice.paid 는 지원 — coupon.* 같은 진짜 미지원 이벤트로 검증."""
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps({"type": "coupon.created", "data": {"object": {}}}).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json()["action"] == "ignored"


@pytest.mark.asyncio
async def test_webhook_checkout_completed_switches_plan(
    client: AsyncClient,
) -> None:
    plan_code, _ = await _ensure_paid_plan_mapping()
    user_id = f"u_{uuid.uuid4().hex[:8]}"
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:16]}"
    stripe_cust_id = f"cus_{uuid.uuid4().hex[:16]}"

    payload = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "subscription",
            "customer": stripe_cust_id,
            "subscription": stripe_sub_id,
            "metadata": {"user_id": user_id, "plan_code": plan_code},
        }},
    }
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json()["action"] == "switched"

    async with async_session_maker() as s:
        sub = await s.scalar(
            select(BillingSubscription)
            .where(BillingSubscription.user_id == user_id)
            .where(BillingSubscription.status == "active")
        )
        assert sub is not None
        side = await s.scalar(
            select(StripeSubscription).where(
                StripeSubscription.subscription_id == sub.id
            )
        )
        assert side is not None
        assert side.stripe_subscription_id == stripe_sub_id


@pytest.mark.asyncio
async def test_webhook_subscription_updated_syncs_status(
    client: AsyncClient,
) -> None:
    plan_code, _ = await _ensure_paid_plan_mapping()
    user_id = f"u_{uuid.uuid4().hex[:8]}"
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:16]}"
    completed = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "subscription",
            "customer": f"cus_{uuid.uuid4().hex[:16]}",
            "subscription": stripe_sub_id,
            "metadata": {"user_id": user_id, "plan_code": plan_code},
        }},
    }
    updated = {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": stripe_sub_id,
            "status": "past_due",
            "current_period_end": 1_900_000_000,
            "cancel_at_period_end": True,
        }},
    }
    with _stripe_enabled():
        await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(completed).encode(),
            headers={"content-type": "application/json"},
        )
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(updated).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json()["action"] == "updated"

    async with async_session_maker() as s:
        side = await s.scalar(
            select(StripeSubscription).where(
                StripeSubscription.stripe_subscription_id == stripe_sub_id
            )
        )
        assert side is not None
        assert side.stripe_status == "past_due"
        assert side.cancel_at_period_end is True


# ── 4. /admin/plan-mapping ─────────────────────────────────


@pytest.mark.asyncio
async def test_admin_plan_mapping_set_and_get_ok(client: AsyncClient) -> None:
    hdr = await _admin_headers(client)
    plan_code = "smb"
    new_price = f"price_test_{uuid.uuid4().hex[:12]}"

    r = await client.post(
        "/api/v1/billing/stripe/admin/plan-mapping",
        json={"plan_code": plan_code, "stripe_price_id": new_price},
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    assert r.json()["stripe_price_id"] == new_price

    r2 = await client.get(
        f"/api/v1/billing/stripe/admin/plan-mapping/{plan_code}",
        headers=hdr,
    )
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_admin_plan_mapping_non_admin_403(client: AsyncClient) -> None:
    hdr = await _staff_headers(client)
    r = await client.post(
        "/api/v1/billing/stripe/admin/plan-mapping",
        json={"plan_code": "smb", "stripe_price_id": "price_x"},
        headers=hdr,
    )
    assert r.status_code == 403
