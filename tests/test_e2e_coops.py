"""C Week 3 — Day 1: CoOps E2E 10 시나리오 (Mock 0).

라우트 단위 테스트 (test_billing/test_content_agents/test_approvals/test_stripe)
가 이미 모듈별로 충분히 검증된 위에, **다중 모듈 일관성** 을 검증한다 —
한 유저가 여러 라우트를 거치며 SaaS 라이프사이클을 완주할 때 plan/quota/usage
상태가 무너지지 않는지.

테스트 철학 (Mock 0):
    - LLM/네트워크 mock 금지
    - 실 LM Studio 호출이 필요한 시나리오는 ``@pytest.mark.slow`` 분리
      (CI 에서는 ``-m "not slow"`` 로 제외 가능). 본 파일은 LM Studio 무관
      시나리오 위주 — DB 상태 직접 조작 + ``record_call`` 직접 호출로
      *원래 라우트와 같은 경로* 를 거쳐 누적 검증.

시나리오 인덱스 (10):
    1. lifecycle_signup_to_free_then_admin_upgrade_to_startup
    2. lifecycle_quota_exhaustion_blocks_all_business_domains  (free 100건 채움 → 4 도메인 모두 429)
    3. lifecycle_admin_upgrade_unblocks_after_429
    4. lifecycle_record_call_aggregates_across_actions  (4 액션 합산 검증)
    5. lifecycle_usage_timeline_returns_daily_points
    6. lifecycle_admin_stats_revenue_reflects_paid_subscribers
    7. lifecycle_plan_downgrade_preserves_calls_count
    8. lifecycle_stripe_disabled_safety_does_not_affect_admin_subscribe
    9. lifecycle_unauthorized_responses_consistent_401  (5 라우트 401 일관)
    10. lifecycle_invalid_plan_returns_400_consistent
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from database import async_session_maker
from models.billing import (
    BillingMonthlyUserUsage,
    BillingPlan,
    BillingSubscription,
)
from saas.helpers import current_year_month
from services.billing import coops_billing
from services.quota import QuotaContext, record_call


# ── 헬퍼 ──────────────────────────────────────────────────────


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


async def _admin_subscribe(
    client: AsyncClient, admin_hdr: dict[str, str], user_id: str, plan_code: str
) -> None:
    r = await client.post(
        "/api/v1/billing/subscribe",
        json={"user_id": user_id, "plan_code": plan_code},
        headers=admin_hdr,
    )
    assert r.status_code == 200, r.text


async def _seed_n_calls(user_id: str, n: int, action: str = "approval_request") -> None:
    """``record_call`` 을 N 회 호출 — 실 라우트와 동일 경로로 monthly usage 누적.

    Mock 0 의 핵심: LLM 호출 대신 ``record_call`` 만 직접 호출 (정상 라우트가
    LLM 후 호출하는 함수 그대로). plan_code 는 현재 활성 구독 기준.
    """
    async with async_session_maker() as s:
        _sub, plan = await coops_billing.get_or_create_active_subscription(s, user_id)
        await s.commit()
        plan_code = plan.code
        plan_quota = plan.monthly_call_quota
        plan_allowed = plan.allowed_models

    for _ in range(n):
        async with async_session_maker() as s:
            quota = QuotaContext(
                user_id=user_id,
                role="developer",
                action=action,
                plan_code=plan_code,
                monthly_call_quota=plan_quota,
                allowed_models=plan_allowed,
                calls_used_before=0,
            )
            await record_call(s, quota, success=True, model_used="FAST", tokens_estimated=100)
            await s.commit()


# ── 1. 신규 가입 → free 자동 → admin 업그레이드 ──────────────────


@pytest.mark.asyncio
async def test_lifecycle_signup_to_free_then_admin_upgrade_to_startup(
    client: AsyncClient,
) -> None:
    """staff 로그인 → /me 가 활성 plan 반환 → admin 이 startup 으로 전환 → /me 갱신.

    conftest 가 staff 를 ent 로 reset 하므로, 본 테스트는 *명시적으로 free → startup
    전환* 을 검증.
    """
    staff_hdr = await _staff_headers(client)
    admin_hdr = await _admin_headers(client)

    # 먼저 free 로 강제 (CoOps free quota = 50, cop003 시드)
    await _admin_subscribe(client, admin_hdr, "staff", "free")
    r = await client.get("/api/v1/billing/me", headers=staff_hdr)
    assert r.status_code == 200
    body = r.json()
    assert body["subscription"]["plan_code"] == "free"
    assert body["subscription"]["monthly_call_quota"] == 50

    # admin 이 startup 으로 전환
    await _admin_subscribe(client, admin_hdr, "staff", "startup")
    r2 = await client.get("/api/v1/billing/me", headers=staff_hdr)
    body2 = r2.json()
    assert body2["subscription"]["plan_code"] == "startup"
    assert body2["subscription"]["monthly_call_quota"] == 500


# ── 2. free 100건 → 4 도메인 모두 429 ─────────────────────────────


@pytest.mark.asyncio
async def test_lifecycle_quota_exhaustion_blocks_all_business_domains(
    client: AsyncClient,
) -> None:
    """free user 가 100 호출 사용 시 video/sns/investor/approval 모두 429.

    LLM 호출 없이 ``record_call`` 100 회로 DB 만 채우고, 실 라우트가 ``enforce_quota``
    에서 차단되는지 검증 (mock 0).
    """
    admin_hdr = await _admin_headers(client)
    uid = "staff"
    await _admin_subscribe(client, admin_hdr, uid, "free")

    # 사용량을 free 한도 (50) 까지 채움
    async with async_session_maker() as s:
        ym = current_year_month()
        monthly = await coops_billing.get_or_create_monthly_usage(s, uid, year_month=ym)
        monthly.calls_count = 50
        await s.commit()

    staff_hdr = await _staff_headers(client)
    payloads = [
        ("/api/v1/video/generate", {
            "topic": "신제품 출시 영상 기획", "duration_sec": 60,
            "audience": "developers", "tone": "professional",
        }),
        ("/api/v1/sns/post", {
            "topic": "신제품 출시 SNS",
            "platforms": ["twitter"],
            "tone": "professional",
        }),
        ("/api/v1/investor/report", {
            "company": "Acme",
            "period": "Q1 2026",
            "key_metrics": {"arr": "$100k"},
        }),
        ("/api/v1/approvals/request", {
            "contract_id": str(uuid.uuid4()),  # 가짜 — enforce_quota 가 먼저 차단
            "approver_role": "manager",
            "title": "결재 요청 quota 테스트",
            "description": "쿼터 초과 검증",
        }),
    ]
    for path, payload in payloads:
        r = await client.post(path, json=payload, headers=staff_hdr)
        assert r.status_code == 429, f"{path} returned {r.status_code} (expected 429)"
        # 표준 헤더
        assert "X-RateLimit-Limit" in r.headers
        assert r.headers["X-RateLimit-Remaining"] == "0"


# ── 3. 한도 초과 후 plan 업그레이드로 해제 ────────────────────────


@pytest.mark.asyncio
async def test_lifecycle_admin_upgrade_unblocks_after_429(
    client: AsyncClient,
) -> None:
    """free 100 → 429, admin 이 smb (5000) 로 전환 → 다시 호출 가능."""
    admin_hdr = await _admin_headers(client)
    uid = "staff"
    await _admin_subscribe(client, admin_hdr, uid, "free")
    async with async_session_maker() as s:
        ym = current_year_month()
        monthly = await coops_billing.get_or_create_monthly_usage(s, uid, year_month=ym)
        monthly.calls_count = 50
        await s.commit()

    staff_hdr = await _staff_headers(client)
    r_blocked = await client.post(
        "/api/v1/approvals/request",
        json={
            "contract_id": str(uuid.uuid4()),
            "approver_role": "manager",
            "title": "blocked",
            "description": "before upgrade",
        },
        headers=staff_hdr,
    )
    assert r_blocked.status_code == 429

    # admin 이 smb (5000) 로 업그레이드
    await _admin_subscribe(client, admin_hdr, uid, "smb")

    r_after = await client.get("/api/v1/billing/me", headers=staff_hdr)
    body = r_after.json()
    assert body["subscription"]["plan_code"] == "smb"
    # 한도 5000, 사용량 50 유지 → 4950 남음
    assert body["usage"]["calls_used"] == 50
    assert body["usage"]["calls_remaining"] == 4950


# ── 4. record_call 누적 일관성 ───────────────────────────────────


@pytest.mark.asyncio
async def test_lifecycle_record_call_aggregates_across_actions(
    client: AsyncClient,
) -> None:
    """video/sns/investor/approval 4 액션을 각 5회씩 record_call → /me usage = 20."""
    admin_hdr = await _admin_headers(client)
    uid = f"e2e-aggr-{uuid.uuid4().hex[:8]}"
    await _admin_subscribe(client, admin_hdr, uid, "smb")  # 5000 limit
    for action in ("video_generate", "sns_post", "investor_report", "approval_request"):
        await _seed_n_calls(uid, 5, action=action)

    async with async_session_maker() as s:
        monthly = await s.scalar(
            select(BillingMonthlyUserUsage)
            .where(BillingMonthlyUserUsage.user_id == uid)
            .where(BillingMonthlyUserUsage.year_month == current_year_month())
        )
        assert monthly is not None
        assert int(monthly.calls_count) == 20
        assert int(monthly.tokens_total) == 2000  # 4×5×100


# ── 5. /usage/timeline ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_lifecycle_usage_timeline_returns_daily_points(
    client: AsyncClient,
) -> None:
    """staff 가 record_call 7회 후 /usage/timeline 이 당일 1점 (count=7) 반환."""
    admin_hdr = await _admin_headers(client)
    await _admin_subscribe(client, admin_hdr, "staff", "smb")
    await _seed_n_calls("staff", 7, action="video_generate")

    staff_hdr = await _staff_headers(client)
    r = await client.get("/api/v1/billing/usage/timeline?days=7", headers=staff_hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "points" in body
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_point = next(
        (p for p in body["points"] if p["date"] == today), None
    )
    assert today_point is not None, f"missing today's point in {body['points']}"
    assert today_point["calls"] >= 7


# ── 6. admin/stats 매출 정합성 ──────────────────────────────────


@pytest.mark.asyncio
async def test_lifecycle_admin_stats_revenue_reflects_paid_subscribers(
    client: AsyncClient,
) -> None:
    """N 명을 smb 로 가입 → admin/stats 의 plan_distribution + revenue 가 반영."""
    admin_hdr = await _admin_headers(client)
    uids = [f"e2e-stats-{uuid.uuid4().hex[:6]}" for _ in range(3)]
    for uid in uids:
        await _admin_subscribe(client, admin_hdr, uid, "smb")

    r = await client.get("/api/v1/billing/admin/stats", headers=admin_hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    plan_codes = {row["plan_code"] for row in body["plan_distribution"]}
    assert {"free", "startup", "smb", "ent"}.issubset(plan_codes)
    smb_row = next(row for row in body["plan_distribution"] if row["plan_code"] == "smb")
    assert smb_row["active_subscribers"] >= 3
    assert smb_row["monthly_revenue_usd"] >= 3 * 499  # 가입 후 즉시 인식


# ── 7. plan downgrade 시 calls_count 보존 ────────────────────────


@pytest.mark.asyncio
async def test_lifecycle_plan_downgrade_preserves_calls_count(
    client: AsyncClient,
) -> None:
    """smb → free 다운그레이드 시 calls_count 유지, 한도만 변경."""
    admin_hdr = await _admin_headers(client)
    uid = f"e2e-down-{uuid.uuid4().hex[:8]}"
    await _admin_subscribe(client, admin_hdr, uid, "smb")
    await _seed_n_calls(uid, 25, action="approval_request")

    # 다운그레이드
    await _admin_subscribe(client, admin_hdr, uid, "free")

    async with async_session_maker() as s:
        monthly = await s.scalar(
            select(BillingMonthlyUserUsage)
            .where(BillingMonthlyUserUsage.user_id == uid)
            .where(BillingMonthlyUserUsage.year_month == current_year_month())
        )
        assert monthly is not None
        assert int(monthly.calls_count) == 25, "다운그레이드는 누적 사용량을 건들지 않아야 함"

        sub = await coops_billing.get_active_subscription(s, uid)
        plan = await coops_billing.get_plan_by_code(s, "free")
        assert sub.plan_id == plan.id  # 활성 plan 만 변경


# ── 8. Stripe 비활성이어도 admin/subscribe 는 영향 없음 ──────────


@pytest.mark.asyncio
async def test_lifecycle_stripe_disabled_safety_does_not_affect_admin_subscribe(
    client: AsyncClient,
) -> None:
    """STRIPE_ENABLED=0 기본값 — /billing/stripe/checkout 503 이어도
    기존 admin /billing/subscribe 는 정상 동작 (수기 plan 부여 가능)."""
    admin_hdr = await _admin_headers(client)
    staff_hdr = await _staff_headers(client)

    # 1) Stripe 라우트는 503 (disabled)
    r_stripe = await client.post(
        "/api/v1/billing/stripe/checkout",
        json={"plan_code": "startup"},
        headers=staff_hdr,
    )
    assert r_stripe.status_code == 503

    # 2) 그래도 admin /subscribe 는 정상
    await _admin_subscribe(client, admin_hdr, "staff", "ent")
    r_me = await client.get("/api/v1/billing/me", headers=staff_hdr)
    assert r_me.json()["subscription"]["plan_code"] == "ent"


# ── 9. 401 응답 일관성 (5 라우트) ───────────────────────────────


@pytest.mark.asyncio
async def test_lifecycle_unauthorized_responses_consistent_401(
    client: AsyncClient,
) -> None:
    """auth 헤더 없이 호출 시 5 라우트가 모두 401 (개별 코드 422/403 등으로 흘러가지 않음)."""
    targets = [
        ("GET", "/api/v1/billing/me", None),
        ("POST", "/api/v1/video/generate", {
            "topic": "ok topic", "duration_sec": 60,
        }),
        ("POST", "/api/v1/sns/post", {
            "topic": "ok topic", "platforms": ["twitter"],
        }),
        ("POST", "/api/v1/investor/report", {
            "company": "Acme", "period": "Q1 2026",
        }),
        ("POST", "/api/v1/billing/stripe/checkout", {
            "plan_code": "startup",
        }),
    ]
    for method, path, payload in targets:
        if method == "GET":
            r = await client.get(path)
        else:
            r = await client.post(path, json=payload)
        assert r.status_code == 401, f"{method} {path} returned {r.status_code}"


# ── 10. invalid plan 400/422 일관 ────────────────────────────────


@pytest.mark.asyncio
async def test_lifecycle_invalid_plan_returns_400_consistent(
    client: AsyncClient,
) -> None:
    """admin/subscribe 와 admin/plan-mapping 모두 unknown plan 에 동일하게 400 응답."""
    admin_hdr = await _admin_headers(client)
    bad_plan = "__no_such_plan__"

    r1 = await client.post(
        "/api/v1/billing/subscribe",
        json={"user_id": "staff", "plan_code": bad_plan},
        headers=admin_hdr,
    )
    assert r1.status_code == 400

    r2 = await client.post(
        "/api/v1/billing/stripe/admin/plan-mapping",
        json={"plan_code": bad_plan, "stripe_price_id": "price_test_x"},
        headers=admin_hdr,
    )
    assert r2.status_code == 400
