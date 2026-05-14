"""E R3-Day 4 — CoOps Inbox retention 통합 테스트 (Mock 0).

라우트:
    POST /api/v1/notifications/admin/purge-old

테스트 시나리오:
    1. admin 외에는 403.
    2. days 파라미터 음수 → 422 (Query ge=0 검증).
    3. days=0 + include_unread=true 면 *현재 시점 이전 모든* 인박스 삭제.
       다만 새로 생성한 row 는 days=0 일 때 cutoff 와 동일 시점이라 보호 어려움 —
       직접 created_at backdate 후 검증.
    4. 기본 (include_unread=false) 은 미독 알림 보존.

테스트 철학 (Mock 0):
    - dev 서버 (localhost) 에 httpx.AsyncClient 호출 + 직접 DB seed.
    - LM/네트워크 mock 없음. ``coops_inbox`` 직접 호출 + ``created_at`` 백데이트.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from database import async_session_maker
from models.notifications import Notification
from services.notifications import coops_inbox


async def _admin(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "admin123"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _staff(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token",
        data={"username": "staff", "password": "staff123"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed_inbox(user_id: str, *, read: bool, age_days: int) -> str:
    """알림 1개 생성 + ``created_at`` 을 N일 전으로 백데이트."""
    nid: str
    async with async_session_maker() as db:
        row = await coops_inbox.create(
            db,
            user_id=user_id,
            kind="system",
            title=f"retain-{uuid.uuid4().hex[:8]}",
            body="ret",
        )
        nid = row.id
        await db.commit()

    async with async_session_maker() as db:
        when = datetime.now(timezone.utc) - timedelta(days=age_days)
        await db.execute(
            update(Notification)
            .where(Notification.id == nid)
            .values(created_at=when, read=read, read_at=when if read else None)
        )
        await db.commit()
    return nid


async def _row_exists(nid: str) -> bool:
    async with async_session_maker() as db:
        row = await db.scalar(
            select(Notification).where(Notification.id == nid)
        )
        return row is not None


# ── 1. RBAC ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_purge_old_requires_admin(client: AsyncClient) -> None:
    headers = await _staff(client)
    r = await client.post(
        "/api/v1/notifications/admin/purge-old?days=30",
        headers=headers,
    )
    assert r.status_code == 403


# ── 2. 입력 검증 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_purge_old_negative_days_returns_422(
    client: AsyncClient,
) -> None:
    headers = await _admin(client)
    r = await client.post(
        "/api/v1/notifications/admin/purge-old?days=-1",
        headers=headers,
    )
    assert r.status_code == 422


# ── 3. 기본 동작: read=True 만 삭제 ───────────────────────────────


@pytest.mark.asyncio
async def test_admin_purge_old_deletes_read_keeps_unread(
    client: AsyncClient,
) -> None:
    headers = await _admin(client)
    user_id = f"purge-{uuid.uuid4().hex[:8]}"

    old_read = await _seed_inbox(user_id, read=True, age_days=100)
    old_unread = await _seed_inbox(user_id, read=False, age_days=100)
    fresh_read = await _seed_inbox(user_id, read=True, age_days=5)

    r = await client.post(
        "/api/v1/notifications/admin/purge-old?days=90",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["days"] == 90
    assert body["include_unread"] is False
    # 글로벌 정리이므로 정확한 카운트는 다른 테스트 누적 영향. 본 row 만 검증.
    assert not await _row_exists(old_read)
    assert await _row_exists(old_unread)
    assert await _row_exists(fresh_read)


# ── 4. include_unread=true 면 미독도 삭제 ───────────────────


@pytest.mark.asyncio
async def test_admin_purge_old_include_unread_deletes_unread_too(
    client: AsyncClient,
) -> None:
    headers = await _admin(client)
    user_id = f"purgef-{uuid.uuid4().hex[:8]}"

    old_unread = await _seed_inbox(user_id, read=False, age_days=200)
    fresh_unread = await _seed_inbox(user_id, read=False, age_days=2)

    r = await client.post(
        "/api/v1/notifications/admin/purge-old?days=90&include_unread=true",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["include_unread"] is True

    assert not await _row_exists(old_unread)
    assert await _row_exists(fresh_unread)
