"""E-Day 4 — CoOps Notifications 라우트 통합 테스트 (Mock 0).

라우트:
    POST   /api/v1/notifications/devices
    DELETE /api/v1/notifications/devices/{token}
    GET    /api/v1/notifications/devices
    POST   /api/v1/notifications/admin/send-test

테스트 철학:
    - PUSH_ENABLED=0 기본 — 등록/조회/폐기 라우트는 토글과 무관 (DB 만).
    - send-test 는 disabled 시 503. enabled + http_disabled 로 dry-run 검증.
    - 외부 HTTP 호출 mock 금지 — 환경변수 ``PUSH_HTTP_DISABLED=1`` 로 skip.
"""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

import pytest
from httpx import AsyncClient


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


def _token() -> str:
    return f"ExponentPushToken[{uuid.uuid4().hex}]"


@contextmanager
def _push_overrides(**overrides: str):
    """coops_push_config 의 필드를 임시로 변경 (테스트 격리)."""
    from services.notifications import coops_push_config

    snapshot = {
        "enabled": coops_push_config.enabled,
        "http_disabled": coops_push_config.http_disabled,
        "expo_access_token": coops_push_config.expo_access_token,
        "api_url": coops_push_config.api_url,
    }
    try:
        for k, v in overrides.items():
            setattr(coops_push_config, k, v)
        yield
    finally:
        for k, v in snapshot.items():
            setattr(coops_push_config, k, v)


# ── 1. 등록 + 조회 + 폐기 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_device_creates_row(client: AsyncClient) -> None:
    staff = await _staff(client)
    tok = _token()
    r = await client.post(
        "/api/v1/notifications/devices",
        json={"expo_push_token": tok, "platform": "android", "device_label": "Pixel 8"},
        headers=staff,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["expo_push_token"] == tok
    assert body["platform"] == "android"
    assert body["device_label"] == "Pixel 8"
    assert body["active"] is True


@pytest.mark.asyncio
async def test_register_device_idempotent_updates_label(client: AsyncClient) -> None:
    staff = await _staff(client)
    tok = _token()
    await client.post(
        "/api/v1/notifications/devices",
        json={"expo_push_token": tok, "platform": "android"},
        headers=staff,
    )
    r2 = await client.post(
        "/api/v1/notifications/devices",
        json={"expo_push_token": tok, "platform": "ios", "device_label": "iPhone 15"},
        headers=staff,
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["platform"] == "ios"
    assert body["device_label"] == "iPhone 15"


@pytest.mark.asyncio
async def test_list_devices_returns_only_own(client: AsyncClient) -> None:
    staff = await _staff(client)
    tok = _token()
    await client.post(
        "/api/v1/notifications/devices",
        json={"expo_push_token": tok, "platform": "android"},
        headers=staff,
    )
    r = await client.get("/api/v1/notifications/devices", headers=staff)
    assert r.status_code == 200
    tokens = [d["expo_push_token"] for d in r.json()["devices"]]
    assert tok in tokens


@pytest.mark.asyncio
async def test_unregister_device_soft_deletes(client: AsyncClient) -> None:
    staff = await _staff(client)
    tok = _token()
    await client.post(
        "/api/v1/notifications/devices",
        json={"expo_push_token": tok, "platform": "android"},
        headers=staff,
    )
    r = await client.delete(
        f"/api/v1/notifications/devices/{tok}",
        headers=staff,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 폐기 후 목록에서 사라짐
    lst = await client.get("/api/v1/notifications/devices", headers=staff)
    tokens = [d["expo_push_token"] for d in lst.json()["devices"]]
    assert tok not in tokens


@pytest.mark.asyncio
async def test_unregister_unknown_token_404(client: AsyncClient) -> None:
    staff = await _staff(client)
    r = await client.delete(
        f"/api/v1/notifications/devices/{_token()}",
        headers=staff,
    )
    assert r.status_code == 404


# ── 2. 권한 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_device_no_auth_401(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/notifications/devices",
        json={"expo_push_token": _token(), "platform": "android"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_register_device_invalid_payload_422(client: AsyncClient) -> None:
    staff = await _staff(client)
    r = await client.post(
        "/api/v1/notifications/devices",
        json={"expo_push_token": "x", "platform": "android"},  # 10 자 미만
        headers=staff,
    )
    assert r.status_code == 422


# ── 3. send-test (disabled / dry-run) ────────────────────────────


@pytest.mark.asyncio
async def test_send_test_disabled_returns_503(client: AsyncClient) -> None:
    admin = await _admin(client)
    with _push_overrides(enabled=False):
        r = await client.post(
            "/api/v1/notifications/admin/send-test",
            json={"user_id": "staff", "title": "t", "body": "b"},
            headers=admin,
        )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_send_test_non_admin_returns_403(client: AsyncClient) -> None:
    staff = await _staff(client)
    r = await client.post(
        "/api/v1/notifications/admin/send-test",
        json={"user_id": "staff", "title": "t", "body": "b"},
        headers=staff,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_send_test_dry_run_returns_skipped_count(client: AsyncClient) -> None:
    """``PUSH_ENABLED=1`` + ``PUSH_HTTP_DISABLED=1`` → 외부 HTTP 호출 없이
    토큰 수만 ``skipped`` 로 반환."""
    admin = await _admin(client)
    staff = await _staff(client)

    # 등록 (2 대)
    tok1, tok2 = _token(), _token()
    for t in (tok1, tok2):
        await client.post(
            "/api/v1/notifications/devices",
            json={"expo_push_token": t, "platform": "android"},
            headers=staff,
        )

    with _push_overrides(enabled=True, http_disabled=True):
        r = await client.post(
            "/api/v1/notifications/admin/send-test",
            json={"user_id": "staff", "title": "결재", "body": "신규 요청 1건"},
            headers=admin,
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"] == 0
    assert body["failed"] == 0
    assert body["skipped"] >= 2
    assert tok1 in body["tokens"]
    assert tok2 in body["tokens"]


@pytest.mark.asyncio
async def test_send_test_no_devices_returns_zero_counts(client: AsyncClient) -> None:
    admin = await _admin(client)
    uid = f"e2e-empty-{uuid.uuid4().hex[:8]}"
    with _push_overrides(enabled=True, http_disabled=True):
        r = await client.post(
            "/api/v1/notifications/admin/send-test",
            json={"user_id": uid, "title": "x", "body": "y"},
            headers=admin,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] == 0
    assert body["failed"] == 0
    assert body["skipped"] == 0
    assert body["tokens"] == []
