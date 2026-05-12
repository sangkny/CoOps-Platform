"""E-R2-Day 1 — CoOps Notification inbox 라우트 통합 테스트 (Mock 0).

라우트:
    GET   /api/v1/notifications/inbox
    PATCH /api/v1/notifications/inbox/{id}/read
    POST  /api/v1/notifications/inbox/read-all

테스트 철학:
    - 외부 push 호출 없음 — DB 만 조작 (``coops_inbox.create`` 직접 호출 OR
      ``coops_notifier.notify`` 호출).
    - 사용자 격리 — staff/manager 가 서로의 알림을 못 본다.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from database import async_session_maker
from services.notifications import coops_inbox, coops_notifier


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


async def _manager(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token",
        data={"username": "manager", "password": "manager123"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed_inbox_for(user_id: str, *, n: int = 1, kind: str = "system") -> list[str]:
    """``coops_inbox.create`` 로 ``user_id`` 에 n개의 알림 row 를 만든다."""
    ids: list[str] = []
    async with async_session_maker() as db:
        for i in range(n):
            row = await coops_inbox.create(
                db,
                user_id=user_id,
                kind=kind,
                title=f"테스트 알림 {i+1}",
                body=f"본문 {i+1}",
                ref_id=f"ref-{uuid.uuid4().hex[:8]}",
                data={"i": i, "tag": "unit"},
            )
            ids.append(row.id)
        await db.commit()
    return ids


# ── 1. 목록 + unread_count ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_inbox_list_returns_seeded_rows(client: AsyncClient) -> None:
    staff = await _staff(client)
    seeded = await _seed_inbox_for("staff", n=3)

    r = await client.get("/api/v1/notifications/inbox", headers=staff)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "staff"
    returned_ids = {it["id"] for it in body["items"]}
    for sid in seeded:
        assert sid in returned_ids
    assert body["unread_count"] >= 3


@pytest.mark.asyncio
async def test_inbox_list_isolated_per_user(client: AsyncClient) -> None:
    """manager 가 만든 알림을 staff 가 볼 수 없어야 한다."""
    staff = await _staff(client)
    mgr_only = await _seed_inbox_for("manager", n=2, kind="approval_request")

    r = await client.get("/api/v1/notifications/inbox", headers=staff)
    assert r.status_code == 200
    body = r.json()
    returned_ids = {it["id"] for it in body["items"]}
    for nid in mgr_only:
        assert nid not in returned_ids


@pytest.mark.asyncio
async def test_inbox_list_unread_only_filter(client: AsyncClient) -> None:
    staff = await _staff(client)
    [first] = await _seed_inbox_for("staff", n=1)
    # 첫 항목 읽음 처리
    await client.patch(
        f"/api/v1/notifications/inbox/{first}/read",
        headers=staff,
    )
    # 두 번째 신규 — 미읽음
    [second] = await _seed_inbox_for("staff", n=1)

    r = await client.get(
        "/api/v1/notifications/inbox?unread_only=true",
        headers=staff,
    )
    assert r.status_code == 200
    body = r.json()
    ids = {it["id"] for it in body["items"]}
    assert second in ids
    assert first not in ids


# ── 2. 읽음 처리 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_read_single_flips_flag(client: AsyncClient) -> None:
    staff = await _staff(client)
    [nid] = await _seed_inbox_for("staff", n=1)

    r = await client.patch(
        f"/api/v1/notifications/inbox/{nid}/read",
        headers=staff,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    lst = await client.get("/api/v1/notifications/inbox", headers=staff)
    item = next(it for it in lst.json()["items"] if it["id"] == nid)
    assert item["read"] is True
    assert item["read_at"] is not None


@pytest.mark.asyncio
async def test_mark_read_twice_returns_404(client: AsyncClient) -> None:
    """이미 읽은 알림에 재차 PATCH 하면 404 (rowcount=0)."""
    staff = await _staff(client)
    [nid] = await _seed_inbox_for("staff", n=1)

    await client.patch(
        f"/api/v1/notifications/inbox/{nid}/read",
        headers=staff,
    )
    r2 = await client.patch(
        f"/api/v1/notifications/inbox/{nid}/read",
        headers=staff,
    )
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_mark_read_other_user_returns_404(client: AsyncClient) -> None:
    """다른 user 의 알림 id 를 PATCH 하면 본인 소유 아니므로 404."""
    staff = await _staff(client)
    [other_id] = await _seed_inbox_for("manager", n=1)

    r = await client.patch(
        f"/api/v1/notifications/inbox/{other_id}/read",
        headers=staff,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_mark_all_read_clears_unread(client: AsyncClient) -> None:
    staff = await _staff(client)
    await _seed_inbox_for("staff", n=3)

    r = await client.post(
        "/api/v1/notifications/inbox/read-all",
        headers=staff,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] >= 3

    lst = await client.get("/api/v1/notifications/inbox", headers=staff)
    assert lst.json()["unread_count"] == 0


# ── 3. notify() helper — push + inbox 통합 ──────────────────────────


@pytest.mark.asyncio
async def test_notifier_notify_writes_inbox_even_when_push_disabled(
    client: AsyncClient,
) -> None:
    """``PUSH_ENABLED=0`` 이어도 ``coops_notifier.notify`` 는 inbox 1행 저장."""
    from services.notifications import coops_push_config

    uid = f"e2e-notify-{uuid.uuid4().hex[:8]}"
    snapshot = coops_push_config.enabled
    coops_push_config.enabled = False
    try:
        async with async_session_maker() as db:
            result = await coops_notifier.notify(
                db,
                user_id=uid,
                title="알림 통합 검증",
                body="push 비활성 + inbox 단독 저장",
                kind="system",
            )
            await db.commit()
    finally:
        coops_push_config.enabled = snapshot

    assert result["inbox_id"] is not None
    assert result["push"]["disabled"] is True

    # 직접 user 로 로그인할 수단이 없으므로, admin send-test 와 무관하게
    # DB 에 row 가 있는지 cross-check
    async with async_session_maker() as db:
        rows = await coops_inbox.list_for_user(db, user_id=uid)
        assert any(r.id == result["inbox_id"] for r in rows)


# ── 4. 권한 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inbox_no_auth_401(client: AsyncClient) -> None:
    r = await client.get("/api/v1/notifications/inbox")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_mark_read_no_auth_401(client: AsyncClient) -> None:
    r = await client.patch(
        "/api/v1/notifications/inbox/non-existent-id/read",
    )
    assert r.status_code == 401
