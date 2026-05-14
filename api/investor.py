"""CoOps Investor IR 콘텐츠 라우트 (Phase 2 → C Week 2, 2026-05-13).

IR 보고서는 SMB plan 이상에서 권장 (HEAVY 모델 사용 — DEBATE 전략 기본).
Free/Startup 도 호출은 가능하지만 PIPELINE 으로 강등되며 출력 품질이 제한된다.
"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import current_user_strict
from database import get_db
from models.content import ContentJob
from schemas.content import (
    ContentJobListResponse,
    ContentJobOut,
    InvestorReportRequest,
    InvestorReportResponse,
)
from services.content_agent import generate_investor_report
from services.notifications import notify_safe
from services.quota import QuotaContext, enforce_quota, record_call

router = APIRouter()


def _job_to_out(job: ContentJob) -> ContentJobOut:
    errs: list[str] = []
    if job.ontology_errors_json:
        try:
            errs = json.loads(job.ontology_errors_json)
        except Exception:
            errs = []
    return ContentJobOut(
        id=job.id,
        user_id=job.user_id,
        action=job.action,
        title=job.title,
        status=job.status,
        plan_code=job.plan_code,
        model_used=job.model_used,
        strategy=job.strategy,
        tokens_estimated=int(job.tokens_estimated or 0),
        latency_ms=job.latency_ms,
        ontology_passed=job.ontology_passed,
        ontology_errors=errs,
        output_text=job.output_text,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


@router.post(
    "/report",
    response_model=InvestorReportResponse,
    summary="분기 IR 보고서 + 슬라이드 생성 (markdown / 슬라이드 outline)",
)
async def generate_investor_route(
    req: InvestorReportRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
    quota: QuotaContext = Depends(enforce_quota("investor_report")),
) -> InvestorReportResponse:
    """PDF 변환은 백로그 — 현재 markdown + 슬라이드 outline 만 반환.

    클라이언트가 markdown 을 `pandoc` 또는 `marp` 로 PDF/슬라이드로 변환.
    """
    started = time.perf_counter()
    success = False
    try:
        job, payload, success = await generate_investor_report(
            db,
            user_id=user["user_id"],
            plan_code=quota.plan_code,
            allowed_models=quota.allowed_models,
            req=req,
        )
        if success:
            await notify_safe(
                db,
                user_id=user["user_id"],
                kind="ir.completed",
                title="IR 보고서가 준비되었습니다",
                body=f"{req.company_name} {req.quarter}",
                ref_id=job.id,
                data={"action": "investor", "job_id": job.id},
            )
        return InvestorReportResponse(**payload)
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        await record_call(
            db, quota, success=success, latency_ms=latency_ms,
        )


@router.get(
    "/jobs",
    response_model=ContentJobListResponse,
    summary="본인의 IR 작업 목록",
)
async def list_investor_jobs(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
    limit: int = Query(20, ge=1, le=100),
) -> ContentJobListResponse:
    user_id = user["user_id"]
    rows = await db.execute(
        select(ContentJob)
        .where(ContentJob.user_id == user_id)
        .where(ContentJob.action == "investor")
        .order_by(ContentJob.created_at.desc())
        .limit(int(limit))
    )
    jobs = [_job_to_out(r) for r in rows.scalars().all()]
    total = (
        await db.scalar(
            select(func.count(ContentJob.id))
            .where(ContentJob.user_id == user_id)
            .where(ContentJob.action == "investor")
        )
    ) or 0
    return ContentJobListResponse(user_id=user_id, jobs=jobs, total=int(total))


@router.get(
    "/jobs/{job_id}",
    response_model=ContentJobOut,
    summary="본인의 IR 작업 단건",
)
async def get_investor_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
) -> ContentJobOut:
    job = await db.get(ContentJob, job_id)
    if not job or job.user_id != user["user_id"] or job.action != "investor":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job 없음")
    return _job_to_out(job)
