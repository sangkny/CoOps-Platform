"""CoOps SaaS Billing (Plan / Subscription / Quota / Usage / Analytics) 회귀 테스트.

테스트 철학 (shared-libraries §"테스트 철학" 2026-05-12 정착):
    - **LLM/네트워크 mock 금지** — 한도 차단 테스트는 enforce_quota 가 *앞에서*
      429 로 차단하도록 DB 상태를 사전 조작 (가짜 응답 X).
    - **실제 PostgreSQL + 실제 라우트** — `client` fixture (httpx ASGI transport).
    - 한 테스트당 **unique user_id** (UUID prefix) — 다른 테스트와 격리.

검증 범위 (14건):
    1. Plan 카탈로그 (공개) — 4종 (free/startup/smb/ent)
    2. /billing/me — Free 자동 부여 (인증 / 무인증)
    3. admin subscribe — 정상 전환 / invalid plan / 403
    4. enforce_quota — Free 한도 차단 (결재 라우트, LLM 호출 무관)
    5. record_call — 성공 → calls_count++ / 실패 → 미증가
    6. admin/stats — 분포 + 매출 구조
    7. quota_headers — 무제한 / clamp 0
"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from database import async_session_maker
from models import (
    BillingMonthlyUserUsage,
    BillingPlan,
    BillingSubscription,
    BillingUsageRecord,
)
from services.billing import (
    current_year_month,
    get_or_create_active_subscription,
    get_or_create_monthly_usage,
)
from services.quota import QuotaContext, record_call


# ── 헬퍼 ─────────────────────────────────────────────────────────────


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


def _unique_user_id(prefix: str) -> str:
    return f"test-{prefix}-{uuid.uuid4().hex[:8]}"


def _unique_contract_number() -> str:
    a = date(2018, 1, 1).toordinal()
    b = date(2038, 12, 31).toordinal()
    d = date.fromordinal(random.randint(a, b))
    return f"CON-{d.strftime('%Y%m%d')}"


async def _create_contract(client: AsyncClient, number: str) -> str:
    r = await client.post(
        "/api/v1/contracts/",
        json={
            "contract_number": number,
            "title": "테스트 계약",
            "party_a": "A",
            "party_b": "B",
        },
    )
    assert r.status_code == 201, r.text
    return number


# ── 1. Plan 카탈로그 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_plans_public_lists_4_tiers(client: AsyncClient) -> None:
    """``GET /billing/plans`` — 인증 없이 공개, 4종 (free/startup/smb/ent)."""
    r = await client.get("/api/v1/billing/plans")
    assert r.status_code == 200, r.text
    body = r.json()
    codes = {p["code"] for p in body["plans"]}
    assert codes == {"free", "startup", "smb", "ent"}
    assert body["default_code"] == "free"

    startup = next(p for p in body["plans"] if p["code"] == "startup")
    assert startup["monthly_call_quota"] == 500
    assert startup["price_usd_per_month"] == 199.0

    smb = next(p for p in body["plans"] if p["code"] == "smb")
    assert smb["price_usd_per_month"] == 499.0
    assert "HEAVY" in smb["allowed_models"]

    ent = next(p for p in body["plans"] if p["code"] == "ent")
    assert ent["monthly_call_quota"] is None
    assert ent["price_usd_per_month"] == 999.0
    assert "CONSENSUS" in ent["allowed_models"]


# ── 2. /billing/me — Free 자동 부여 ──────────────────────────────────


@pytest.mark.asyncio
async def test_billing_me_returns_subscription_for_staff(
    client: AsyncClient,
) -> None:
    """``GET /billing/me`` — staff 로그인 시 subscription + usage 반환."""
    headers = await _staff_headers(client)
    r = await client.get("/api/v1/billing/me", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "staff"
    assert body["subscription"]["plan_code"] in {"free", "startup", "smb", "ent"}
    assert body["usage"]["year_month"] == current_year_month()


@pytest.mark.asyncio
async def test_billing_me_no_auth_returns_401(client: AsyncClient) -> None:
    r = await client.get("/api/v1/billing/me")
    assert r.status_code == 401


# ── 3. admin subscribe 분기 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_subscribe_switches_plan_and_records_previous(
    client: AsyncClient,
) -> None:
    """admin → user 를 startup → smb 로 전환, previous_plan_code 정확."""
    user_id = _unique_user_id("switch")
    admin = await _admin_headers(client)

    r1 = await client.post(
        "/api/v1/billing/subscribe",
        headers=admin,
        json={"user_id": user_id, "plan_code": "startup"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["plan_code"] == "startup"

    r2 = await client.post(
        "/api/v1/billing/subscribe",
        headers=admin,
        json={"user_id": user_id, "plan_code": "smb"},
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["plan_code"] == "smb"
    assert body2["previous_plan_code"] == "startup"

    async with async_session_maker() as s:
        rows = (
            await s.execute(
                select(BillingSubscription).where(
                    BillingSubscription.user_id == user_id
                )
            )
        ).scalars().all()
        statuses = sorted(r.status for r in rows)
        assert "active" in statuses
        assert "cancelled" in statuses
        active = [r for r in rows if r.status == "active"]
        assert len(active) == 1


@pytest.mark.asyncio
async def test_admin_subscribe_invalid_plan_returns_400(
    client: AsyncClient,
) -> None:
    """없는 plan_code → 백엔드 ValueError → 400 BAD_REQUEST.

    ADK 는 Pydantic regex 로 422 를 즉시 반환했지만, CoOps 는 plan 종류가
    런타임에 확장될 수 있도록 (Plus / Calendar 등) regex 를 두지 않고 backend
    validation 으로 처리한다 (더 유연).
    """
    user_id = _unique_user_id("invalid")
    admin = await _admin_headers(client)
    r = await client.post(
        "/api/v1/billing/subscribe",
        headers=admin,
        json={"user_id": user_id, "plan_code": "platinum"},
    )
    assert r.status_code == 400, r.text
    body = r.json()
    detail = body.get("detail") or ""
    assert "platinum" in str(detail) or "unknown" in str(detail).lower()


@pytest.mark.asyncio
async def test_admin_subscribe_by_non_admin_returns_403(
    client: AsyncClient,
) -> None:
    headers = await _staff_headers(client)
    r = await client.post(
        "/api/v1/billing/subscribe",
        headers=headers,
        json={"user_id": "staff", "plan_code": "smb"},
    )
    assert r.status_code == 403


# ── 4. enforce_quota — 한도 차단 (결재 라우트, LM Studio 무관) ───────


async def _force_user_to_plan_with_usage(
    user_id: str, plan_code: str, calls_count: int
) -> None:
    async with async_session_maker() as s:
        plan = await s.scalar(
            select(BillingPlan).where(BillingPlan.code == plan_code)
        )
        assert plan is not None, f"plan {plan_code} 가 시드되지 않음"
        sub, _ = await get_or_create_active_subscription(s, user_id)
        sub.plan_id = plan.id
        sub.status = "active"
        monthly = await get_or_create_monthly_usage(s, user_id)
        monthly.calls_count = int(calls_count)
        monthly.tokens_total = 0
        await s.commit()


async def _reset_user_to_ent_unlimited(user_id: str) -> None:
    async with async_session_maker() as s:
        plan = await s.scalar(select(BillingPlan).where(BillingPlan.code == "ent"))
        assert plan is not None
        sub, _ = await get_or_create_active_subscription(s, user_id)
        sub.plan_id = plan.id
        sub.status = "active"
        monthly = await get_or_create_monthly_usage(s, user_id)
        monthly.calls_count = 0
        monthly.tokens_total = 0
        await s.commit()


@pytest.mark.asyncio
async def test_enforce_quota_blocks_at_free_limit_on_approval_request(
    client: AsyncClient,
) -> None:
    """staff 가 Free (50/m) 한도 도달 → 결재 요청 시 429.

    Ontology 검증 / DB write 등 결재 로직 *전*에 ``enforce_quota`` 가 막으므로,
    Contract 가 없어도 429 가 우선. 테스트 후 staff 를 Ent 로 복원해 conftest
    autouse fixture 와 별개로 다른 테스트에 영향 없음.
    """
    user_id = "staff"
    try:
        await _force_user_to_plan_with_usage(user_id, "free", 50)
        headers = await _staff_headers(client)
        r = await client.post(
            "/api/v1/approvals/request",
            headers=headers,
            json={
                "contract_number": "CON-99990101",
                "assigned_approver_id": "MGR-1",
                "requester_id": "REQ-1",
                "request_date": datetime.now().date().isoformat(),
                "description": "quota 차단 테스트",
            },
        )
        assert r.status_code == 429, r.text
        body = r.json()
        detail = body.get("detail") or {}
        assert detail.get("error") == "quota_exceeded"
        assert detail.get("plan_code") == "free"
        assert detail.get("calls_limit") == 50
        assert r.headers.get("X-RateLimit-Limit") == "50"
        assert r.headers.get("X-RateLimit-Remaining") == "0"
        assert int(r.headers.get("X-RateLimit-Reset", "0")) > 0
    finally:
        await _reset_user_to_ent_unlimited(user_id)


# ── 5. record_call — 성공/실패 분기 ─────────────────────────────────


@pytest.mark.asyncio
async def test_record_call_success_increments_calls_count() -> None:
    """``record_call(success=True)`` → calls_count, tokens_total 증가."""
    user_id = _unique_user_id("rec-ok")
    async with async_session_maker() as s:
        await get_or_create_active_subscription(s, user_id)
        before = await get_or_create_monthly_usage(s, user_id)
        before_calls = int(before.calls_count or 0)
        before_tokens = int(before.tokens_total or 0)
        await s.commit()

    ctx = QuotaContext(
        user_id=user_id,
        role="staff",
        action="approval_request",
        plan_code="free",
        monthly_call_quota=50,
        allowed_models="FAST",
        calls_used_before=before_calls,
    )

    async with async_session_maker() as s:
        await record_call(
            s, ctx,
            success=True,
            model_used="local/test",
            tokens_estimated=200,
            latency_ms=88,
        )
        await s.commit()

    async with async_session_maker() as s:
        row = await s.scalar(
            select(BillingMonthlyUserUsage)
            .where(BillingMonthlyUserUsage.user_id == user_id)
            .where(BillingMonthlyUserUsage.year_month == current_year_month())
        )
        assert row is not None
        assert int(row.calls_count) == before_calls + 1
        assert int(row.tokens_total) == before_tokens + 200


@pytest.mark.asyncio
async def test_record_call_failure_does_not_increment() -> None:
    """``record_call(success=False)`` → BillingUsageRecord 만 남고 calls_count 미증가."""
    user_id = _unique_user_id("rec-fail")
    async with async_session_maker() as s:
        await get_or_create_active_subscription(s, user_id)
        before = await get_or_create_monthly_usage(s, user_id)
        before_calls = int(before.calls_count or 0)
        await s.commit()

    ctx = QuotaContext(
        user_id=user_id,
        role="staff",
        action="approval_request",
        plan_code="free",
        monthly_call_quota=50,
        allowed_models="FAST",
        calls_used_before=before_calls,
    )

    async with async_session_maker() as s:
        await record_call(
            s, ctx,
            success=False,
            model_used="local/test",
            tokens_estimated=100,
            latency_ms=42,
        )
        await s.commit()

    async with async_session_maker() as s:
        row = await s.scalar(
            select(BillingMonthlyUserUsage)
            .where(BillingMonthlyUserUsage.user_id == user_id)
            .where(BillingMonthlyUserUsage.year_month == current_year_month())
        )
        assert row is not None
        assert int(row.calls_count) == before_calls
        rec = await s.scalar(
            select(BillingUsageRecord)
            .where(BillingUsageRecord.user_id == user_id)
            .where(BillingUsageRecord.success.is_(False))
        )
        assert rec is not None
        assert rec.action == "approval_request"


# ── 6. approval_request → record_call 통합 (성공 시 calls_count+=1) ─


@pytest.mark.asyncio
async def test_approval_request_success_increments_quota(
    client: AsyncClient,
) -> None:
    """결재 요청이 성공하면 staff 의 monthly calls_count 가 1 증가."""
    cn = _unique_contract_number()
    await _create_contract(client, cn)
    headers = await _staff_headers(client)

    async with async_session_maker() as s:
        before = await get_or_create_monthly_usage(s, "staff")
        before_calls = int(before.calls_count or 0)
        await s.commit()

    r = await client.post(
        "/api/v1/approvals/request",
        headers=headers,
        json={
            "contract_number": cn,
            "assigned_approver_id": "MGR-2",
            "requester_id": "REQ-2",
            "request_date": datetime.now().date().isoformat(),
            "description": "쿼터 증가 통합 테스트",
            "amount": "1000",
            "currency": "USD",
        },
    )
    assert r.status_code == 201, r.text

    async with async_session_maker() as s:
        after = await get_or_create_monthly_usage(s, "staff")
        assert int(after.calls_count) == before_calls + 1


# ── 7. admin/stats — 매출·플랜 분포 ─────────────────────────────────


@pytest.mark.asyncio
async def test_admin_stats_returns_structure(client: AsyncClient) -> None:
    admin = await _admin_headers(client)
    r = await client.get("/api/v1/billing/admin/stats", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["year_month"] == current_year_month()
    assert body["total_active_subscribers"] >= 0
    assert body["total_monthly_revenue_usd"] >= 0
    assert {p["plan_code"] for p in body["plan_distribution"]} == {
        "free",
        "startup",
        "smb",
        "ent",
    }
    free_dist = next(
        p for p in body["plan_distribution"] if p["plan_code"] == "free"
    )
    assert free_dist["price_usd_per_month"] == 0
    assert free_dist["monthly_revenue_usd"] == 0


@pytest.mark.asyncio
async def test_admin_stats_non_admin_returns_403(client: AsyncClient) -> None:
    headers = await _staff_headers(client)
    r = await client.get("/api/v1/billing/admin/stats", headers=headers)
    assert r.status_code == 403


# ── 8. quota_headers — 무제한 / clamp ──────────────────────────────


def test_quota_headers_unlimited() -> None:
    from services.quota import quota_headers

    h = quota_headers(None, 1000)
    assert h["X-RateLimit-Limit"] == "-1"
    assert h["X-RateLimit-Remaining"] == "-1"
    assert int(h["X-RateLimit-Reset"]) > 0


def test_quota_headers_remaining_clamps_at_zero() -> None:
    from services.quota import quota_headers

    h = quota_headers(50, 75)
    assert h["X-RateLimit-Limit"] == "50"
    assert h["X-RateLimit-Remaining"] == "0"
