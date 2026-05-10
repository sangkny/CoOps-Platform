"""결재 — BUSINESS Ontology + Lore (Week 5 Day 4)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.ontology import validate_business_ontology
from models.business import Approval, ApprovalLore, Contract
from schemas.business import (
    ApprovalApproveBody,
    ApprovalRejectBody,
    ApprovalRequestBody,
    ApprovalResponse,
)
from services.approval_ontology_payload import (
    ontology_payload_decision,
    ontology_payload_request,
)

router = APIRouter()


def _append_lore(
    db: AsyncSession,
    approval_id: str,
    event: str,
    detail: dict[str, Any],
) -> None:
    db.add(
        ApprovalLore(
            id=str(uuid.uuid4()),
            approval_id=approval_id,
            event_type=event,
            detail_json=json.dumps(detail, ensure_ascii=False),
        ),
    )


@router.post(
    "/request",
    response_model=ApprovalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="결재 요청 (승인자 ID 필수 + Ontology 검증)",
)
async def request_approval(
    body: ApprovalRequestBody,
    db:   AsyncSession = Depends(get_db),
) -> Approval:
    c = await db.scalar(
        select(Contract).where(Contract.contract_number == body.contract_number),
    )
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"계약 번호 없음: {body.contract_number}",
        )

    payload = ontology_payload_request(body, c.contract_number)
    await validate_business_ontology(payload)

    appr = Approval(
        id=str(uuid.uuid4()),
        contract_id=c.id,
        step_order=body.step_order,
        approver_role=body.approver_role,
        assigned_approver_id=body.assigned_approver_id,
        requester_id=body.requester_id,
        request_date=body.request_date,
        description=(body.description or "").strip() or None,
        amount=body.amount,
        currency=body.currency.strip().upper() if body.currency else None,
        actor_id=None,
        status="pending",
        comment=None,
        finalized=False,
    )
    db.add(appr)
    await db.flush()

    _append_lore(
        db,
        appr.id,
        "request",
        {
            "contract_number": c.contract_number,
            "assigned_approver_id": appr.assigned_approver_id,
            "requester_id": appr.requester_id,
            "amount":       str(appr.amount) if appr.amount is not None else None,
            "currency":     appr.currency,
        },
    )
    await db.refresh(appr)
    return appr


@router.get(
    "/pending",
    response_model=list[ApprovalResponse],
    summary="대기(pending) 결재 목록",
)
async def list_pending(
    db: AsyncSession = Depends(get_db),
) -> list[Approval]:
    q = (
        select(Approval)
        .where(Approval.status == "pending")
        .order_by(Approval.created_at.desc())
    )
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


@router.post(
    "/{approval_id}/approve",
    response_model=ApprovalResponse,
    summary="승인",
)
async def approve_approval(
    approval_id: str,
    body:          ApprovalApproveBody,
    db:            AsyncSession = Depends(get_db),
) -> Approval:
    appr = await db.get(Approval, approval_id)
    if not appr:
        raise HTTPException(status_code=404, detail="결재 없음")
    if appr.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"대기 상태만 승인 가능 (현재={appr.status})",
        )

    c = await db.get(Contract, appr.contract_id)
    if not c:
        raise HTTPException(status_code=500, detail="연결 계약 없음")

    payload = ontology_payload_decision(
        contract_number=c.contract_number,
        requester_id=appr.requester_id,
        request_date=appr.request_date,
        description=appr.description,
        approval_status="approved",
        approver_id=body.approver_id,
        amount=appr.amount,
        currency=appr.currency,
    )
    await validate_business_ontology(payload)

    appr.status = "approved"
    appr.actor_id = body.approver_id
    appr.finalized = True
    appr.comment = None
    await db.flush()

    _append_lore(
        db,
        appr.id,
        "approved",
        {"approver_id": body.approver_id, "contract_number": c.contract_number},
    )
    await db.refresh(appr)
    return appr


@router.post(
    "/{approval_id}/reject",
    response_model=ApprovalResponse,
    summary="반려 + 사유",
)
async def reject_approval(
    approval_id: str,
    body:          ApprovalRejectBody,
    db:            AsyncSession = Depends(get_db),
) -> Approval:
    appr = await db.get(Approval, approval_id)
    if not appr:
        raise HTTPException(status_code=404, detail="결재 없음")
    if appr.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"대기 상태만 반려 가능 (현재={appr.status})",
        )

    c = await db.get(Contract, appr.contract_id)
    if not c:
        raise HTTPException(status_code=500, detail="연결 계약 없음")

    payload = ontology_payload_decision(
        contract_number=c.contract_number,
        requester_id=appr.requester_id,
        request_date=appr.request_date,
        description=appr.description,
        approval_status="rejected",
        approver_id=body.approver_id,
        amount=appr.amount,
        currency=appr.currency,
    )
    await validate_business_ontology(payload)

    appr.status = "rejected"
    appr.actor_id = body.approver_id
    appr.comment = body.reason
    appr.finalized = True
    await db.flush()

    _append_lore(
        db,
        appr.id,
        "rejected",
        {
            "approver_id":     body.approver_id,
            "reason":          body.reason,
            "contract_number": c.contract_number,
        },
    )
    await db.refresh(appr)
    return appr
