"""CoOps 콘텐츠 에이전트 라우트 통합 테스트 (Phase 2 → C Week 2).

테스트 철학 (Mock 금지):
    - 입력 검증 (422), Quota 차단 (429), RBAC (401/403), DB ContentJob 생성/조회
      는 LM Studio 없이도 검증 가능 — 본 스위트가 커버한다.
    - 실 LLM 호출 결과 (script JSON 파싱·Ontology 통과) 는 LM Studio 가
      필요하므로 `@pytest.mark.integration` 으로 표시 후 LM Studio 가용
      환경 (`LM_STUDIO_BASE_URL` 응답) 에서만 실행 (백로그).

LM Studio 가 없으면 `generate_video/sns/investor` 호출이 timeout/error 로
``status='failed'`` 응답을 반환. 본 테스트는 그 경로 (200 + status=failed)
까지 검증한다 — orchestrator 가 환경에 따라 fallback 으로 동작.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from database import async_session_maker
from models.content import ContentJob


async def _staff_headers(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token",
        data={"username": "staff", "password": "staff123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── 1. 인증/입력 검증 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_video_generate_no_auth_returns_401(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/video/generate",
        json={"title": "TestBrand 30주년", "topic": "감사 메시지", "duration_seconds": 15},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_video_generate_invalid_duration_returns_422(client: AsyncClient) -> None:
    headers = await _staff_headers(client)
    r = await client.post(
        "/api/v1/video/generate",
        json={"title": "T", "topic": "x", "duration_seconds": 45},
        headers=headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_sns_post_requires_platforms(client: AsyncClient) -> None:
    headers = await _staff_headers(client)
    r = await client.post(
        "/api/v1/sns/post",
        json={"topic": "신제품 출시", "platforms": []},
        headers=headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_investor_report_invalid_quarter_returns_422(client: AsyncClient) -> None:
    headers = await _staff_headers(client)
    r = await client.post(
        "/api/v1/investor/report",
        json={
            "company_name": "TestCo",
            "quarter": "2026Q5",  # invalid (Q1-Q4 only)
            "audience": "vc",
        },
        headers=headers,
    )
    assert r.status_code == 422


# ── 2. Quota 차단 (LM Studio 무관) ────────────────────────────────


async def _force_user_to_plan_with_usage(
    user_id: str, plan_code: str, calls_count: int
) -> None:
    from models.billing import BillingPlan
    from services.billing import (
        get_or_create_active_subscription,
        get_or_create_monthly_usage,
    )

    async with async_session_maker() as s:
        plan = await s.scalar(
            select(BillingPlan).where(BillingPlan.code == plan_code)
        )
        assert plan is not None
        sub, _ = await get_or_create_active_subscription(s, user_id)
        sub.plan_id = plan.id
        sub.status = "active"
        monthly = await get_or_create_monthly_usage(s, user_id)
        monthly.calls_count = int(calls_count)
        await s.commit()


async def _reset_user_to_ent_unlimited(user_id: str) -> None:
    from models.billing import BillingPlan
    from services.billing import (
        get_or_create_active_subscription,
        get_or_create_monthly_usage,
    )

    async with async_session_maker() as s:
        plan = await s.scalar(select(BillingPlan).where(BillingPlan.code == "ent"))
        assert plan is not None
        sub, _ = await get_or_create_active_subscription(s, user_id)
        sub.plan_id = plan.id
        sub.status = "active"
        monthly = await get_or_create_monthly_usage(s, user_id)
        monthly.calls_count = 0
        await s.commit()


@pytest.mark.asyncio
async def test_video_generate_quota_blocked_at_free_limit(client: AsyncClient) -> None:
    user_id = "staff"
    try:
        await _force_user_to_plan_with_usage(user_id, "free", 50)
        headers = await _staff_headers(client)
        r = await client.post(
            "/api/v1/video/generate",
            json={"title": "쿼터 차단", "topic": "테스트", "duration_seconds": 15},
            headers=headers,
        )
        assert r.status_code == 429, r.text
        detail = r.json().get("detail") or {}
        assert detail.get("error") == "quota_exceeded"
        assert detail.get("plan_code") == "free"
        assert r.headers.get("X-RateLimit-Remaining") == "0"
    finally:
        await _reset_user_to_ent_unlimited(user_id)


@pytest.mark.asyncio
async def test_sns_post_quota_blocked_at_free_limit(client: AsyncClient) -> None:
    user_id = "staff"
    try:
        await _force_user_to_plan_with_usage(user_id, "free", 50)
        headers = await _staff_headers(client)
        r = await client.post(
            "/api/v1/sns/post",
            json={"topic": "차단 테스트", "platforms": ["twitter"]},
            headers=headers,
        )
        assert r.status_code == 429
        assert r.headers.get("X-RateLimit-Limit") == "50"
    finally:
        await _reset_user_to_ent_unlimited(user_id)


@pytest.mark.asyncio
async def test_investor_report_quota_blocked_at_free_limit(client: AsyncClient) -> None:
    user_id = "staff"
    try:
        await _force_user_to_plan_with_usage(user_id, "free", 50)
        headers = await _staff_headers(client)
        r = await client.post(
            "/api/v1/investor/report",
            json={
                "company_name": "BlockedCo",
                "quarter": "2026Q2",
                "audience": "vc",
            },
            headers=headers,
        )
        assert r.status_code == 429
    finally:
        await _reset_user_to_ent_unlimited(user_id)


# ── 3. ContentJob 영속화 (LM Studio 미가용 경로도 200) ────────────


@pytest.mark.asyncio
async def test_video_generate_creates_content_job_row(client: AsyncClient) -> None:
    """LM Studio 가 없어도 ContentJob row 가 생성되고 status 가 기록되어야 한다.

    LM Studio 있으면 ``completed`` + script. 없으면 ``failed`` + error_message.
    어느 경우든 200 응답 + job_id + status 가 반환된다.
    """
    headers = await _staff_headers(client)
    title = f"테스트 {uuid.uuid4().hex[:8]}"
    r = await client.post(
        "/api/v1/video/generate",
        json={
            "title": title,
            "topic": "CoOps SaaS 베타 출시 안내 — Cursor 와 CoOps 의 협업 이야기",
            "duration_seconds": 60,
            "audience": "스타트업 창업자",
            "tone": "energetic",
            "cta": "지금 무료 베타에 신청하세요",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "job_id" in body
    assert body["status"] in {"completed", "failed"}

    async with async_session_maker() as s:
        job = await s.get(ContentJob, body["job_id"])
        assert job is not None
        assert job.user_id == "staff"
        assert job.action == "video"
        assert job.title == title
        assert job.status in {"completed", "failed"}
        assert job.plan_code is not None
        assert job.strategy is not None
        assert job.latency_ms is not None


@pytest.mark.asyncio
async def test_sns_post_creates_content_job_row(client: AsyncClient) -> None:
    headers = await _staff_headers(client)
    r = await client.post(
        "/api/v1/sns/post",
        json={
            "topic": "신제품 출시 — Cursor IDE 확장",
            "platforms": ["twitter", "linkedin"],
            "tone": "professional",
            "audience": "개발자",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in {"completed", "failed"}

    async with async_session_maker() as s:
        job = await s.get(ContentJob, body["job_id"])
        assert job is not None
        assert job.action == "sns"


@pytest.mark.asyncio
async def test_investor_report_creates_content_job_row(client: AsyncClient) -> None:
    headers = await _staff_headers(client)
    r = await client.post(
        "/api/v1/investor/report",
        json={
            "company_name": "CoOps Inc.",
            "quarter": "2026Q2",
            "highlights": ["베타 10명 온보딩", "MRR $2K"],
            "metrics": [
                {"name": "MRR", "value": "$2,000", "direction": "up"},
                {"name": "베타 유저", "value": "10", "direction": "up"},
            ],
            "risks": ["LLM 호스팅 비용 변동"],
            "audience": "vc",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in {"completed", "failed"}

    async with async_session_maker() as s:
        job = await s.get(ContentJob, body["job_id"])
        assert job is not None
        assert job.action == "investor"
        assert "2026Q2" in (job.title or "")


# ── 4. ContentJob 조회 라우트 ───────────────────────────────────


@pytest.mark.asyncio
async def test_video_jobs_list_returns_only_own_video_jobs(client: AsyncClient) -> None:
    headers = await _staff_headers(client)
    r = await client.post(
        "/api/v1/video/generate",
        json={
            "title": "list-test",
            "topic": "스타트업의 베타 출시 안내 영상 대본 (목록 조회용)",
            "duration_seconds": 15,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    lst = await client.get("/api/v1/video/jobs?limit=5", headers=headers)
    assert lst.status_code == 200
    body = lst.json()
    assert body["user_id"] == "staff"
    job_ids = {j["id"] for j in body["jobs"]}
    assert job_id in job_ids
    for j in body["jobs"]:
        assert j["action"] == "video"


@pytest.mark.asyncio
async def test_video_jobs_detail_404_for_other_action(client: AsyncClient) -> None:
    headers = await _staff_headers(client)
    r = await client.post(
        "/api/v1/sns/post",
        json={
            "topic": "베타 출시 안내 — Twitter 짧은 본문",
            "platforms": ["twitter"],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    sns_job_id = r.json()["job_id"]
    r2 = await client.get(f"/api/v1/video/jobs/{sns_job_id}", headers=headers)
    assert r2.status_code == 404
