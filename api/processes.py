"""업무 프로세스 생성·실행(스켈레톤)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.business import Contract, Process
from schemas.business import ProcessCreate, ProcessResponse
from services.process_runner import ProcessRunner

router = APIRouter()
_runner = ProcessRunner()


@router.get("/", response_model=list[ProcessResponse])
async def list_processes(db: AsyncSession = Depends(get_db)) -> list[Process]:
    rows = (
        (await db.execute(select(Process).order_by(Process.created_at.desc())))
        .scalars()
        .all()
    )
    return list(rows)


@router.post("/", response_model=ProcessResponse, status_code=status.HTTP_201_CREATED)
async def create_process(
    payload: ProcessCreate,
    db: AsyncSession = Depends(get_db),
) -> Process:
    if payload.contract_id:
        c = await db.get(Contract, payload.contract_id)
        if not c:
            raise HTTPException(status_code=404, detail="계약 없음")
    proc = Process(
        id=str(uuid.uuid4()),
        name=payload.name,
        description=payload.description,
        workflow_json=payload.workflow_json,
        status="idle",
        contract_id=payload.contract_id,
    )
    db.add(proc)
    await db.flush()
    await db.refresh(proc)
    return proc


@router.post("/{process_id}/start", response_model=ProcessResponse)
async def start_process(
    process_id: str,
    db: AsyncSession = Depends(get_db),
) -> Process:
    proc = await db.get(Process, process_id)
    if not proc:
        raise HTTPException(status_code=404, detail="프로세스 없음")

    stub = await _runner.run_placeholder(proc.workflow_json, proc.name)
    if not stub.get("ok"):
        proc.status = "failed"
    else:
        proc.status = "running"
    await db.flush()
    await db.refresh(proc)
    return proc
