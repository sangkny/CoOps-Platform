"""Week 5 Day 4 — 결재 API + BUSINESS Ontology (통합, Postgres 가정)."""
from __future__ import annotations

import random
from datetime import date, datetime

import pytest
from httpx import AsyncClient


def _unique_contract_number() -> str:
    """동일 DB 재실행 시 CON 번호 충돌 방지 (유효 YYYYMMDD)."""
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


@pytest.mark.asyncio
async def test_approval_request_and_pending_and_approve(client: AsyncClient) -> None:
    cn = _unique_contract_number()
    await _create_contract(client, cn)

    req = await client.post(
        "/api/v1/approvals/request",
        json={
            "contract_number":           cn,
            "assigned_approver_id":      "EMP-APPROVER",
            "requester_id":               "EMP-REQ",
            "request_date":               datetime.now().date().isoformat(),
            "description":               "라이선스 갱신 결재",
            "amount":                     "1000000",
            "currency":                   "KRW",
            "step_order":                 1,
            "approver_role":              "manager",
        },
    )
    assert req.status_code == 201, req.text
    aid = req.json()["id"]
    assert req.json()["status"] == "pending"

    pend = await client.get("/api/v1/approvals/pending")
    assert pend.status_code == 200
    ids = {x["id"] for x in pend.json()}
    assert aid in ids

    ap = await client.post(
        f"/api/v1/approvals/{aid}/approve",
        json={"approver_id": "EMP-APPROVER"},
    )
    assert ap.status_code == 200, ap.text
    assert ap.json()["status"] == "approved"
    assert ap.json()["actor_id"] == "EMP-APPROVER"


@pytest.mark.asyncio
async def test_reject_with_reason(client: AsyncClient) -> None:
    cn = _unique_contract_number()
    await _create_contract(client, cn)
    req = await client.post(
        "/api/v1/approvals/request",
        json={
            "contract_number":      cn,
            "assigned_approver_id": "MGR-01",
            "requester_id":          "REQ-01",
            "request_date":          datetime.now().date().isoformat(),
            "description":         "반려 테스트",
        },
    )
    assert req.status_code == 201
    aid = req.json()["id"]

    rj = await client.post(
        f"/api/v1/approvals/{aid}/reject",
        json={"approver_id": "MGR-01", "reason": "예산 초과"},
    )
    assert rj.status_code == 200, rj.text
    b = rj.json()
    assert b["status"] == "rejected"
    assert "예산" in (b.get("comment") or "")


@pytest.mark.asyncio
async def test_ontology_amount_requires_currency(client: AsyncClient) -> None:
    cn = _unique_contract_number()
    await _create_contract(client, cn)
    bad = await client.post(
        "/api/v1/approvals/request",
        json={
            "contract_number":      cn,
            "assigned_approver_id": "X",
            "requester_id":          "Y",
            "request_date":          datetime.now().date().isoformat(),
            "description":         "통화 누락",
            "amount":                "5000",
        },
    )
    assert bad.status_code == 422
    detail = bad.json().get("detail") or {}
    assert "ontology" in detail or "summary" in str(detail)


@pytest.mark.asyncio
async def test_invalid_contract_number_ontology(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/approvals/request",
        json={
            "contract_number":      "BAD-ID",
            "assigned_approver_id": "A",
            "requester_id":          "B",
            "request_date":          str(date(2026, 6, 4)),
            "description":         "형식 오류",
        },
    )
    assert r.status_code == 422
