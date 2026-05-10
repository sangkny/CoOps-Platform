"""계약 API."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import require_role
from database import get_db
from models.business import Contract
from schemas.business import (
    ContractAnalyzeBody,
    ContractAnalyzeResponse,
    ContractCreate,
    ContractResponse,
)
from services.contract_analyzer import ContractAnalyzer

router = APIRouter()


@router.get("/", response_model=list[ContractResponse], summary="계약 목록")
async def list_contracts(
    db: AsyncSession = Depends(get_db),
) -> list[Contract]:
    rows = (
        (
            await db.execute(
                select(Contract).order_by(Contract.created_at.desc()),
            )
        ).scalars().all()
    )
    return list(rows)


@router.post("/", response_model=ContractResponse, status_code=status.HTTP_201_CREATED)
async def create_contract(
    payload: ContractCreate,
    db: AsyncSession = Depends(get_db),
) -> Contract:
    exists = await db.scalar(
        select(Contract.id).where(Contract.contract_number == payload.contract_number),
    )
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"계약 번호 충돌: {payload.contract_number}",
        )
    obj = Contract(
        contract_number=payload.contract_number,
        title=payload.title,
        party_a=payload.party_a,
        party_b=payload.party_b,
        body_text=payload.body_text,
        effective_date=payload.effective_date,
        status=payload.status.value,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


@router.post(
    "/analyze",
    response_model=ContractAnalyzeResponse,
    summary="DEBATE 계약 분석 + BUSINESS 재검증 + Lore 저장",
)
async def analyze_contract(
    body: ContractAnalyzeBody,
    db:   AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("staff", "admin")),
) -> ContractAnalyzeResponse:
    svc = ContractAnalyzer()
    try:
        payload = await svc.analyze(db, body.contract_text, body.contract_number)
        return ContractAnalyzeResponse(**payload)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.get("/{contract_id}", response_model=ContractResponse)
async def get_contract(
    contract_id: str,
    db: AsyncSession = Depends(get_db),
) -> Contract:
    obj = await db.get(Contract, contract_id)
    if not obj:
        raise HTTPException(status_code=404, detail="계약 없음")
    return obj
