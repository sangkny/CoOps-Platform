"""E-R2-Day 2 — 결재 hook 자동 알림 통합 테스트 (Mock 0).

검증 시나리오:
    1. ``POST /approvals/request`` → 결재자 inbox 에 ``approval_request`` 알림 1행.
    2. ``POST /approvals/{id}/approve`` → 요청자 inbox 에 ``approval_decision``
       (``approved``).
    3. ``POST /approvals/{id}/reject`` → 요청자 inbox 에 ``approval_decision``
       (``rejected``) + 사유 본문 포함.
    4. push 활성 + http_disabled (dry-run) 에서도 inbox 정상 생성.

테스트 철학:
    - 외부 HTTP 호출 없음 — ``PUSH_HTTP_DISABLED=1`` 또는 ``PUSH_ENABLED=0``.
    - DB 만 직접 read — ``coops_inbox.list_for_user`` 로 알림 row 확인.
"""
from __future__ import annotations

import random
import uuid
from contextlib import contextmanager
from datetime import date, datetime

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


async def _manager_headers(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token",
        data={"username": "manager", "password": "mgr123"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _unique_contract_number() -> str:
    a = date(2018, 1, 1).toordinal()
    b = date(2038, 12, 31).toordinal()
    d = date.fromordinal(random.randint(a, b))
    return f"CON-{d.strftime('%Y%m%d')}"


def _u(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


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


@contextmanager
def _push_overrides(**overrides):
    from services.notifications import coops_push_config

    snapshot = {
        "enabled": coops_push_config.enabled,
        "http_disabled": coops_push_config.http_disabled,
    }
    try:
        for k, v in overrides.items():
            setattr(coops_push_config, k, v)
        yield
    finally:
        for k, v in snapshot.items():
            setattr(coops_push_config, k, v)


async def _inbox_rows_for(user_id: str) -> list:
    async with async_session_maker() as db:
        rows = await coops_inbox.list_for_user(db, user_id=user_id, limit=200)
        return list(rows)


# ── 1. /approvals/request → approver inbox ────────────────────────


@pytest.mark.asyncio
async def test_approval_request_writes_approver_inbox(client: AsyncClient) -> None:
    cn = _unique_contract_number()
    await _create_contract(client, cn)

    approver = _u("APR")
    requester = _u("REQ")
    hdrs = await _staff_headers(client)

    r = await client.post(
        "/api/v1/approvals/request",
        json={
            "contract_number": cn,
            "assigned_approver_id": approver,
            "requester_id": requester,
            "request_date": datetime.now().date().isoformat(),
            "description": "결재 hook 검증",
            "amount": "100000",
            "currency": "KRW",
            "step_order": 1,
            "approver_role": "manager",
        },
        headers=hdrs,
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]

    rows = await _inbox_rows_for(approver)
    assert len(rows) >= 1
    assert any(
        row.kind == "approval_request"
        and row.ref_id == aid
        and cn in row.body
        for row in rows
    ), [r.kind for r in rows]


# ── 2. approve → requester inbox ─────────────────────────────────


@pytest.mark.asyncio
async def test_approve_writes_requester_inbox_approved(client: AsyncClient) -> None:
    cn = _unique_contract_number()
    await _create_contract(client, cn)

    approver = _u("APR")
    requester = _u("REQ")
    hdrs = await _staff_headers(client)

    req = await client.post(
        "/api/v1/approvals/request",
        json={
            "contract_number": cn,
            "assigned_approver_id": approver,
            "requester_id": requester,
            "request_date": datetime.now().date().isoformat(),
            "description": "approve hook",
        },
        headers=hdrs,
    )
    aid = req.json()["id"]

    mgr = await _manager_headers(client)
    ap = await client.post(
        f"/api/v1/approvals/{aid}/approve",
        json={"approver_id": approver},
        headers=mgr,
    )
    assert ap.status_code == 200, ap.text

    rows = await _inbox_rows_for(requester)
    decisions = [r for r in rows if r.kind == "approval_decision" and r.ref_id == aid]
    assert decisions, "approved 알림이 requester inbox 에 없음"
    title_text = decisions[0].title
    assert "승인" in title_text


# ── 3. reject → requester inbox + 사유 본문 ────────────────────────


@pytest.mark.asyncio
async def test_reject_writes_requester_inbox_with_reason(client: AsyncClient) -> None:
    cn = _unique_contract_number()
    await _create_contract(client, cn)

    approver = _u("APR")
    requester = _u("REQ")
    hdrs = await _staff_headers(client)

    req = await client.post(
        "/api/v1/approvals/request",
        json={
            "contract_number": cn,
            "assigned_approver_id": approver,
            "requester_id": requester,
            "request_date": datetime.now().date().isoformat(),
            "description": "reject hook",
        },
        headers=hdrs,
    )
    aid = req.json()["id"]

    mgr = await _manager_headers(client)
    rj = await client.post(
        f"/api/v1/approvals/{aid}/reject",
        json={"approver_id": approver, "reason": "예산 초과"},
        headers=mgr,
    )
    assert rj.status_code == 200

    rows = await _inbox_rows_for(requester)
    decisions = [r for r in rows if r.kind == "approval_decision" and r.ref_id == aid]
    assert decisions
    body_text = decisions[0].body
    assert "예산 초과" in body_text


# ── 4. push 활성 + dry-run 에서도 inbox 생성 ──────────────────────


@pytest.mark.asyncio
async def test_request_hook_inbox_works_with_push_dry_run(client: AsyncClient) -> None:
    cn = _unique_contract_number()
    await _create_contract(client, cn)

    approver = _u("APR-DRY")
    requester = _u("REQ-DRY")
    hdrs = await _staff_headers(client)

    with _push_overrides(enabled=True, http_disabled=True):
        r = await client.post(
            "/api/v1/approvals/request",
            json={
                "contract_number": cn,
                "assigned_approver_id": approver,
                "requester_id": requester,
                "request_date": datetime.now().date().isoformat(),
                "description": "dry-run hook",
            },
            headers=hdrs,
        )
        assert r.status_code == 201

    rows = await _inbox_rows_for(approver)
    assert any(row.kind == "approval_request" for row in rows)


# ── 5. approver_id 없으면 hook noop (필드는 optional 이 아님 → 422 케이스 외) ─


@pytest.mark.asyncio
async def test_request_hook_does_not_break_when_approver_blank(
    client: AsyncClient,
) -> None:
    """``assigned_approver_id`` 공백 시 ``_notify_safe`` 가 noop 인지 검증.

    실제 라우트는 ``assigned_approver_id`` 를 required 로 받지만, 위 helper
    가 빈 문자열에 대해서도 안전한지 cross-check (회귀 안전망).
    """
    from api.approvals import _notify_safe

    async with async_session_maker() as db:
        await _notify_safe(
            db,
            user_id="",
            kind="approval_request",
            title="x",
            body="y",
        )
        # 예외 없이 통과하면 OK — DB rollback 으로 부작용 없음
        await db.rollback()
