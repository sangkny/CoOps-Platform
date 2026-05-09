"""결재 라인."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.business import Approval, Contract
from schemas.business import ApprovalCreate, ApprovalResponse, ApprovalUpdate

router = APIRouter()


@router.post("/", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def register_approval(
    payload: ApprovalCreate,
    db: AsyncSession = Depends(get_db),
) -> Approval:
    c = await db.get(Contract, payload.contract_id)
    if not c:
        raise HTTPException(status_code=404, detail="계약 없음")
    appr = Approval(
        id=str(uuid.uuid4()),
        contract_id=payload.contract_id,
        step_order=payload.step_order,
        approver_role=payload.approver_role,
        status="pending",
        comment=None,
        finalized=False,
    )
    db.add(appr)
    await db.flush()
    await db.refresh(appr)
    return appr


@router.patch("/{approval_id}", response_model=ApprovalResponse)
async def update_approval(
    approval_id: str,
    payload: ApprovalUpdate,
    db: AsyncSession = Depends(get_db),
) -> Approval:
    appr = await db.get(Approval, approval_id)
    if not appr:
        raise HTTPException(status_code=404, detail="결재 레코드 없음")
    appr.status = payload.status.value
    appr.comment = payload.comment
    appr.finalized = payload.status.value in {"approved", "rejected"}
    await db.flush()
    await db.refresh(appr)
    return appr


@router.get("/", response_model=list[ApprovalResponse], summary="결재 목록(전체)")
async def list_approvals(
    db: AsyncSession = Depends(get_db),
    contract_id: str | None = None,
) -> list[Approval]:
    q = select(Approval).order_by(Approval.created_at.desc())
    if contract_id:
        q = q.where(Approval.contract_id == contract_id)
    rows = (await db.execute(q)).scalars().all()
    return list(rows)
