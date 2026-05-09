"""계약 API."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.business import Contract
from schemas.business import ContractCreate, ContractResponse

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


@router.get("/{contract_id}", response_model=ContractResponse)
async def get_contract(
    contract_id: str,
    db: AsyncSession = Depends(get_db),
) -> Contract:
    obj = await db.get(Contract, contract_id)
    if not obj:
        raise HTTPException(status_code=404, detail="계약 없음")
    return obj
