"""C Week 3 Day 5 — Beta Onboarding 라우트 통합 테스트 (Mock 0).

CoOps ``POST /api/v1/billing/admin/onboard-batch`` 라우트:
    - 정상 일괄 부여 (3명 → 모두 ok)
    - admin 권한 없으면 403
    - 빈 user_ids / 100 초과 user_ids → 422
    - 잘못된 plan_code → 각 entry 가 failed (전체는 200)
    - 중복 user_id → failed=duplicate_or_empty_user_id
    - welcome_note echo 검증
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


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


def _uids(n: int) -> list[str]:
    return [f"beta-{uuid.uuid4().hex[:8]}-{i}" for i in range(n)]


# ── 1. 정상 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_onboard_batch_three_users_all_ok(client: AsyncClient) -> None:
    admin = await _admin_headers(client)
    user_ids = _uids(3)
    r = await client.post(
        "/api/v1/billing/admin/onboard-batch",
        json={
            "user_ids": user_ids,
            "plan_code": "startup",
            "welcome_note": "CoOps 베타에 오신 것을 환영합니다.",
        },
        headers=admin,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requested"] == 3
    assert body["succeeded"] == 3
    assert body["failed"] == 0
    assert body["plan_code"] == "startup"
    assert body["welcome_note"].startswith("CoOps 베타")
    for e in body["entries"]:
        assert e["status"] == "ok"
        assert e["plan_code"] == "startup"


# ── 2. 권한 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_onboard_batch_non_admin_returns_403(client: AsyncClient) -> None:
    staff = await _staff_headers(client)
    r = await client.post(
        "/api/v1/billing/admin/onboard-batch",
        json={"user_ids": _uids(1), "plan_code": "startup"},
        headers=staff,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_onboard_batch_no_auth_returns_401(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/billing/admin/onboard-batch",
        json={"user_ids": _uids(1), "plan_code": "startup"},
    )
    assert r.status_code == 401


# ── 3. 입력 검증 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_onboard_batch_empty_user_ids_422(client: AsyncClient) -> None:
    admin = await _admin_headers(client)
    r = await client.post(
        "/api/v1/billing/admin/onboard-batch",
        json={"user_ids": [], "plan_code": "startup"},
        headers=admin,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_onboard_batch_more_than_100_users_422(client: AsyncClient) -> None:
    admin = await _admin_headers(client)
    r = await client.post(
        "/api/v1/billing/admin/onboard-batch",
        json={"user_ids": _uids(101), "plan_code": "startup"},
        headers=admin,
    )
    assert r.status_code == 422


# ── 4. 잘못된 plan_code — 모든 entry 가 failed, 응답은 200 ────────


@pytest.mark.asyncio
async def test_onboard_batch_unknown_plan_failed_entries(client: AsyncClient) -> None:
    admin = await _admin_headers(client)
    r = await client.post(
        "/api/v1/billing/admin/onboard-batch",
        json={"user_ids": _uids(2), "plan_code": "__no_such_plan__"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["succeeded"] == 0
    assert body["failed"] == 2
    for e in body["entries"]:
        assert e["status"] == "failed"
        assert e["error"]


# ── 5. 중복 user_id 처리 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_onboard_batch_duplicate_user_id_marked_failed(client: AsyncClient) -> None:
    admin = await _admin_headers(client)
    uid = f"beta-dup-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        "/api/v1/billing/admin/onboard-batch",
        json={"user_ids": [uid, uid, uid], "plan_code": "smb"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 2
    statuses = [e["status"] for e in body["entries"]]
    assert statuses == ["ok", "failed", "failed"]
    for e in body["entries"][1:]:
        assert "duplicate" in (e.get("error") or "")
