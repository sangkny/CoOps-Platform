"""BUSINESS OntologyValidator용 검증 페이로드 조립."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from schemas.business import ApprovalRequestBody


def ontology_payload_request(body: ApprovalRequestBody, contract_number: str) -> dict[str, Any]:
    desc = (body.description or "").strip() or "결재 요청"
    d: dict[str, Any] = {
        "contract_id":    contract_number,
        "requester_id":   body.requester_id,
        "request_date":   body.request_date.isoformat(),
        "description":    desc,
    }
    if body.amount is not None:
        d["amount"] = float(body.amount)
    if body.currency is not None:
        d["currency"] = body.currency.strip().upper()
    return d


def ontology_payload_decision(
    *,
    contract_number:  str,
    requester_id:     str,
    request_date:     date,
    description:      str | None,
    approval_status:  str,
    approver_id:      str,
    amount:           Decimal | None,
    currency:         str | None,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "contract_id":       contract_number,
        "requester_id":      requester_id,
        "request_date":      request_date.isoformat(),
        "description":       (description or "").strip() or "결재 요청",
        "approval_status":   approval_status,
        "approver_id":       approver_id,
    }
    if amount is not None:
        d["amount"] = float(amount)
    if currency:
        d["currency"] = currency
    return d
