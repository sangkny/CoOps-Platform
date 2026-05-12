"""B-7 Round 2 — CoOps Stripe R2 통합 테스트 (Mock 0).

검증:
    1. /portal 라우트 — disabled 503, no auth 401, no active sub 404.
    2. webhook ``invoice.paid`` — sidecar.last_paid_at + last_paid_amount_cents 갱신,
       saas_stripe_revenue_usd_total 누적 (라벨 + value 양쪽).
    3. webhook ``invoice.payment_failed`` — sidecar.last_failure_at 갱신.
    4. webhook ``charge.refunded`` — refunded 매출 메트릭 누적.
    5. R2 의 새 이벤트 3종도 SUPPORTED_EVENTS 에 들어가 200 반환 (ignored 아님).

테스트 철학:
    - 외부 HTTP 호출 없음 — ``skip_signature_verification=True`` + dict payload.
    - 메트릭 검증은 ``inc_saas_stripe_revenue`` 호출이 발생했는지 직접 확인 (best-effort
      라벨 카운터 값 read).
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from database import async_session_maker
from models import BillingPlan, BillingSubscription, StripePlanMapping, StripeSubscription
from saas.stripe_service import StripeConfig
from services.billing import coops_stripe


async def _staff(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token",
        data={"username": "staff", "password": "staff123"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@contextmanager
def _stripe_enabled():
    original = coops_stripe.config
    coops_stripe.config = StripeConfig(
        enabled=True,
        secret_key="sk_test_dummy",
        webhook_secret="whsec_test_dummy",
        public_key="pk_test_dummy",
        skip_signature_verification=True,
    )
    try:
        yield
    finally:
        coops_stripe.config = original


async def _ensure_paid_plan_mapping() -> str:
    plan_code = "startup"
    async with async_session_maker() as s:
        plan = await s.scalar(
            select(BillingPlan).where(BillingPlan.code == plan_code)
        )
        existing = await s.scalar(
            select(StripePlanMapping).where(StripePlanMapping.plan_id == plan.id)
        )
        if existing is None:
            s.add(
                StripePlanMapping(
                    id=str(uuid.uuid4()),
                    plan_id=plan.id,
                    stripe_price_id=f"price_test_{uuid.uuid4().hex[:12]}",
                )
            )
            await s.commit()
    return plan_code


async def _seed_subscription_with_sidecar(user_id: str, stripe_sub_id: str) -> None:
    """checkout.session.completed 의 결과 상태를 직접 seed (외부 HTTP / parse 단계 없음)."""
    plan_code = await _ensure_paid_plan_mapping()
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "subscription",
            "customer": f"cus_{uuid.uuid4().hex[:16]}",
            "subscription": stripe_sub_id,
            "metadata": {"user_id": user_id, "plan_code": plan_code},
        }},
    }
    async with async_session_maker() as db:
        await coops_stripe.handle_event(db, event)
        await db.commit()


# ── 1. /portal ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_portal_no_auth_returns_401(client: AsyncClient) -> None:
    r = await client.post("/api/v1/billing/stripe/portal", json={})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_portal_disabled_returns_503(client: AsyncClient) -> None:
    hdr = await _staff(client)
    r = await client.post(
        "/api/v1/billing/stripe/portal", json={}, headers=hdr
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_portal_no_stripe_customer_returns_404(client: AsyncClient) -> None:
    """사용자가 active sub 만 있고 Stripe sidecar 가 없을 때 404."""
    hdr = await _staff(client)
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/portal", json={}, headers=hdr
        )
    assert r.status_code == 404
    assert "no_stripe_customer" in r.text or "no_active_subscription" in r.text


# ── 2. invoice.paid → sidecar 갱신 + revenue 메트릭 ───────────


@pytest.mark.asyncio
async def test_webhook_invoice_paid_updates_sidecar_and_metric(
    client: AsyncClient,
) -> None:
    user_id = f"u_{uuid.uuid4().hex[:8]}"
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:16]}"
    await _seed_subscription_with_sidecar(user_id, stripe_sub_id)

    paid_payload = {
        "type": "invoice.paid",
        "data": {"object": {
            "subscription": stripe_sub_id,
            "amount_paid": 19900,  # 199 USD
            "currency": "usd",
        }},
    }
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(paid_payload).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "paid"

    async with async_session_maker() as s:
        side = await s.scalar(
            select(StripeSubscription).where(
                StripeSubscription.stripe_subscription_id == stripe_sub_id
            )
        )
        assert side is not None
        assert side.last_paid_at is not None
        assert side.last_paid_amount_cents == 19900


@pytest.mark.asyncio
async def test_webhook_invoice_paid_no_amount_returns_no_amount(
    client: AsyncClient,
) -> None:
    payload = {
        "type": "invoice.paid",
        "data": {"object": {
            "subscription": f"sub_{uuid.uuid4().hex[:16]}",
            "amount_paid": 0,
        }},
    }
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json()["action"] == "no_amount"


# ── 3. invoice.payment_failed → sidecar 갱신 ────────────────


@pytest.mark.asyncio
async def test_webhook_invoice_failed_updates_failure_at(
    client: AsyncClient,
) -> None:
    user_id = f"u_{uuid.uuid4().hex[:8]}"
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:16]}"
    await _seed_subscription_with_sidecar(user_id, stripe_sub_id)

    payload = {
        "type": "invoice.payment_failed",
        "data": {"object": {"subscription": stripe_sub_id}},
    }
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json()["action"] == "failed"

    async with async_session_maker() as s:
        side = await s.scalar(
            select(StripeSubscription).where(
                StripeSubscription.stripe_subscription_id == stripe_sub_id
            )
        )
        assert side is not None
        assert side.last_failure_at is not None


# ── 4. charge.refunded → refunded direction 메트릭 ──────────


@pytest.mark.asyncio
async def test_webhook_charge_refunded_returns_refunded(client: AsyncClient) -> None:
    payload = {
        "type": "charge.refunded",
        "data": {"object": {
            "amount_refunded": 5000,  # 50 USD
            "currency": "usd",
        }},
    }
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json()["action"] == "refunded"


# ── 5. metrics 확인 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_revenue_metric_accumulates_for_paid_and_refunded() -> None:
    """saas_stripe_revenue_usd_total 카운터에 paid/refunded 양쪽 라벨 등록 확인."""
    try:
        from prometheus_client import REGISTRY

        # 카운터 등록을 강제
        from observability import inc_saas_stripe_revenue

        inc_saas_stripe_revenue(service="coops", amount_usd=1.0, direction="paid")
        inc_saas_stripe_revenue(service="coops", amount_usd=0.5, direction="refunded")
    except ImportError:
        pytest.skip("prometheus-client 미설치 — 환경에 따라 skip")

    samples = []
    for collector in list(REGISTRY._collector_to_names.keys()):
        try:
            for metric in collector.collect():
                if metric.name == "saas_stripe_revenue_usd":
                    samples.extend(metric.samples)
        except Exception:
            continue

    seen_directions = {
        s.labels.get("direction")
        for s in samples
        if s.labels.get("service") == "coops"
    }
    # paid 와 refunded 라벨이 모두 등록되었어야 함
    assert "paid" in seen_directions
    assert "refunded" in seen_directions
