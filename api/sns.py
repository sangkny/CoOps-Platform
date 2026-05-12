"""CoOps SNS 콘텐츠 라우트 (Phase 2 → C Week 2, 2026-05-13)."""
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
    SNSPostRequest,
    SNSPostResponse,
)
from services.content_agent import generate_sns_posts
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
    "/post",
    response_model=SNSPostResponse,
    summary="플랫폼별 SNS 본문 생성 (Twitter/LinkedIn/Instagram)",
)
async def generate_sns_route(
    req: SNSPostRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
    quota: QuotaContext = Depends(enforce_quota("sns_post")),
) -> SNSPostResponse:
    started = time.perf_counter()
    success = False
    try:
        _job, payload, success = await generate_sns_posts(
            db,
            user_id=user["user_id"],
            plan_code=quota.plan_code,
            allowed_models=quota.allowed_models,
            req=req,
        )
        return SNSPostResponse(**payload)
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        await record_call(
            db, quota, success=success, latency_ms=latency_ms,
        )


@router.get(
    "/jobs",
    response_model=ContentJobListResponse,
    summary="본인의 SNS 작업 목록",
)
async def list_sns_jobs(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
    limit: int = Query(20, ge=1, le=100),
) -> ContentJobListResponse:
    user_id = user["user_id"]
    rows = await db.execute(
        select(ContentJob)
        .where(ContentJob.user_id == user_id)
        .where(ContentJob.action == "sns")
        .order_by(ContentJob.created_at.desc())
        .limit(int(limit))
    )
    jobs = [_job_to_out(r) for r in rows.scalars().all()]
    total = (
        await db.scalar(
            select(func.count(ContentJob.id))
            .where(ContentJob.user_id == user_id)
            .where(ContentJob.action == "sns")
        )
    ) or 0
    return ContentJobListResponse(user_id=user_id, jobs=jobs, total=int(total))


@router.get(
    "/jobs/{job_id}",
    response_model=ContentJobOut,
    summary="본인의 SNS 작업 단건",
)
async def get_sns_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
) -> ContentJobOut:
    job = await db.get(ContentJob, job_id)
    if not job or job.user_id != user["user_id"] or job.action != "sns":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job 없음")
    return _job_to_out(job)
