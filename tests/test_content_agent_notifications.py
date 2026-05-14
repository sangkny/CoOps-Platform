"""E-R3-Day 1 — Content agent 완료 시 자동 푸시 hook 통합 테스트 (Mock 0).

검증 시나리오:
    1. ``POST /video/generate`` 성공 시 호출자 inbox 에 ``video.completed`` 알림.
    2. ``POST /sns/post`` 성공 시 호출자 inbox 에 ``sns.completed`` 알림.
    3. ``POST /investor/report`` 성공 시 호출자 inbox 에 ``ir.completed`` 알림.
    4. LM Studio 미가용 (``status='failed'``) 인 경우 알림이 생성되지 않음.

테스트 철학 (Mock 0):
    - LM Studio 가 응답하면 ``completed`` → hook 실행 → inbox row 1 추가.
    - LM Studio 미가용이면 ``failed`` → hook 미실행 → inbox row 추가 없음.
    - 두 경로 모두 200 응답을 받으므로 inbox 차이로만 hook 작동을 검증.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from database import async_session_maker
from services.notifications import coops_inbox


async def _staff_headers(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token",
        data={"username": "staff", "password": "staff123"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _inbox_kinds_for(user_id: str, kind: str, ref_id: str) -> list:
    async with async_session_maker() as db:
        rows = await coops_inbox.list_for_user(db, user_id=user_id, limit=200)
    return [r for r in rows if r.kind == kind and r.ref_id == ref_id]


@pytest.mark.asyncio
async def test_video_generate_completion_triggers_inbox_notification(
    client: AsyncClient,
) -> None:
    headers = await _staff_headers(client)
    title = f"er3-vid-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        "/api/v1/video/generate",
        json={
            "title": title,
            "topic": "CoOps SaaS 베타 출시 안내 - Cursor 와 협업하는 SMB 자동화",
            "duration_seconds": 60,
            "audience": "스타트업 창업자",
            "tone": "energetic",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = await _inbox_kinds_for("staff", kind="video.completed", ref_id=body["job_id"])
    if body["status"] == "completed":
        assert len(rows) == 1, f"video.completed inbox row 가 정확히 1개여야 함, got {len(rows)}"
        assert title in rows[0].body
    else:
        # LM Studio 미가용 — hook 미호출
        assert len(rows) == 0


@pytest.mark.asyncio
async def test_sns_post_completion_triggers_inbox_notification(
    client: AsyncClient,
) -> None:
    headers = await _staff_headers(client)
    topic = f"er3-sns-{uuid.uuid4().hex[:8]} 신제품 출시"
    r = await client.post(
        "/api/v1/sns/post",
        json={
            "topic": topic,
            "platforms": ["twitter", "linkedin"],
            "tone": "professional",
            "audience": "개발자",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = await _inbox_kinds_for("staff", kind="sns.completed", ref_id=body["job_id"])
    if body["status"] == "completed":
        assert len(rows) == 1
        assert topic in rows[0].body
    else:
        assert len(rows) == 0


@pytest.mark.asyncio
async def test_investor_report_completion_triggers_inbox_notification(
    client: AsyncClient,
) -> None:
    headers = await _staff_headers(client)
    company = f"ER3-IR-{uuid.uuid4().hex[:6]}"
    r = await client.post(
        "/api/v1/investor/report",
        json={
            "company_name": company,
            "quarter": "2026Q2",
            "highlights": ["베타 10명 온보딩"],
            "metrics": [{"name": "MRR", "value": "$2K", "direction": "up"}],
            "risks": ["LLM 비용"],
            "audience": "vc",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = await _inbox_kinds_for("staff", kind="ir.completed", ref_id=body["job_id"])
    if body["status"] == "completed":
        assert len(rows) == 1
        assert "2026Q2" in rows[0].body
        assert company in rows[0].body
    else:
        assert len(rows) == 0


@pytest.mark.asyncio
async def test_notify_safe_helper_noop_with_blank_user(
    client: AsyncClient,  # noqa: ARG001 - fixture 만 활용
) -> None:
    """``notify_safe`` 헬퍼가 빈 user_id 에 대해 noop 인지 확인."""
    from services.notifications import notify_safe

    async with async_session_maker() as db:
        # 예외 없이 통과해야 함
        await notify_safe(
            db,
            user_id="",
            kind="ir.completed",
            title="x",
            body="y",
        )
        await db.rollback()
