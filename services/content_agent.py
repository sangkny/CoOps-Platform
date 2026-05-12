"""CoOps 콘텐츠 생성 에이전트 (Phase 2 → C Week 2, 2026-05-13).

3종 (Video / SNS / Investor) 의 공통 워크플로:
    1. ``allowed_models`` 검사 — plan tier 의 모델 한도와 요청 strategy 매칭
    2. Prompt 빌더 — action 별 시스템/사용자 프롬프트 + JSON 스키마 가이드
    3. Orchestrator (shared.agents.Orchestrator) PIPELINE 실행
    4. 출력 파싱 (JSON 코드블록 추출 → Pydantic 유효성 검증)
    5. BUSINESS Ontology 검증 (요약 텍스트 + 필수 메타)
    6. ``ContentJob`` row 영속화 + 결과 반환

LLM 미가용/오류 시 ``status='failed' + error_message`` 로 저장하고 응답을 반환.
호출 측에서 비동기로 ``record_call(success=False)`` 가 호출되어 quota 가 차감되지 않는다.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from agents.orchestrator import Orchestrator, OrchestraStrategy
from ontology.base import OntologyDomain
from ontology.validator import OntologyValidator
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import ContentJob
from schemas.content import (
    InvestorReport,
    InvestorReportRequest,
    InvestorSlide,
    SNSPostPlatformOutput,
    SNSPostRequest,
    VideoGenerateRequest,
    VideoScene,
    VideoScript,
)

log = logging.getLogger("services.content_agent")


# ── 공통 유틸리티 ────────────────────────────────────────────────────


def _extract_json(text: str) -> dict[str, Any] | None:
    """LLM 응답에서 첫 번째 JSON 객체를 추출.

    1. ```json ... ``` 코드블록 우선
    2. 그 외 첫 ``{`` 부터 균형 잡힌 끝 ``}`` 까지
    """
    if not text:
        return None
    block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    candidate = block.group(1) if block else None
    if not candidate:
        m = re.search(r"\{[\s\S]*\}", text)
        candidate = m.group(0) if m else None
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        try:
            cleaned = re.sub(r",(\s*[}\]])", r"\1", candidate)
            return json.loads(cleaned)
        except Exception:
            return None


async def _create_job(
    db: AsyncSession,
    *,
    user_id: str,
    action: str,
    title: str | None,
    input_payload: dict[str, Any],
    plan_code: str | None,
    strategy: str,
) -> ContentJob:
    job = ContentJob(
        id=str(uuid.uuid4()),
        user_id=user_id,
        action=action,
        title=title,
        input_json=json.dumps(input_payload, ensure_ascii=False),
        status="running",
        plan_code=plan_code,
        strategy=strategy,
    )
    db.add(job)
    await db.flush()
    return job


async def _finalize_job(
    db: AsyncSession,
    job: ContentJob,
    *,
    success: bool,
    output_text: str | None,
    output_payload: dict[str, Any] | None,
    model_used: str | None,
    latency_ms: int,
    ontology_passed: bool | None,
    ontology_errors: list[str] | None,
    error_message: str | None = None,
) -> None:
    job.status = "completed" if success else "failed"
    job.output_text = (output_text or "")[:65500]
    job.output_json = (
        json.dumps(output_payload, ensure_ascii=False)[:65500]
        if output_payload is not None
        else None
    )
    job.model_used = model_used
    job.latency_ms = int(latency_ms)
    job.ontology_passed = ontology_passed
    job.ontology_errors_json = (
        json.dumps(ontology_errors[:12], ensure_ascii=False)
        if ontology_errors
        else None
    )
    job.error_message = error_message
    job.completed_at = datetime.now(timezone.utc)
    await db.flush()


def _select_strategy_for_plan(
    allowed_models: str, requested: str | None
) -> OrchestraStrategy:
    """plan 의 ``allowed_models`` CSV 와 요청 strategy 를 매칭.

    Plan 별 강제 (Free/Startup=FAST, SMB=FAST+HEAVY, Ent=ALL):
        - FAST only → PIPELINE 만 허용
        - FAST,HEAVY → PIPELINE / DEBATE
        - ALL (CONSENSUS 포함) → 모두
    요청이 plan 허용을 초과하면 자동으로 안전한 PIPELINE 으로 강등 (백로그: 403).
    """
    models = {m.strip().upper() for m in (allowed_models or "FAST").split(",") if m.strip()}
    req = (requested or "pipeline").lower()
    if req == "consensus" and "CONSENSUS" in models:
        return OrchestraStrategy.CONSENSUS
    if req == "debate" and "HEAVY" in models:
        return OrchestraStrategy.DEBATE
    return OrchestraStrategy.PIPELINE


# ── Video Agent ─────────────────────────────────────────────────────


def _build_video_prompt(req: VideoGenerateRequest) -> str:
    audience = req.audience or "일반 소비자"
    cta = req.cta or "기본 CTA"
    sections = {
        15: "3~4개 짧은 컷 (각 3-5초)",
        60: "5~7개 컷 (10초 내외)",
        180: "9~12개 컷 (15~25초)",
    }.get(req.duration_seconds, "5~7개 컷")
    return (
        f"당신은 CoOps SaaS 의 SMB 광고 영상 대본 작가입니다. "
        f"BUSINESS Ontology 규칙을 준수하세요 — 허위 광고 표현, 의료/의학적 효능 단정, "
        f"비교 광고 (자사·타사 직접 비교), PII (이름/전화/주민번호) 는 금지.\n\n"
        f"제목: {req.title}\n"
        f"주제: {req.topic}\n"
        f"길이: {req.duration_seconds}초 ({sections})\n"
        f"대상: {audience}\n"
        f"톤: {req.tone}\n"
        f"CTA: {cta}\n\n"
        f"다음 JSON 형식만으로 응답하세요 (코드블록 안에):\n"
        f"```json\n"
        f"{{\n"
        f'  "title": "...",\n'
        f'  "duration_seconds": {req.duration_seconds},\n'
        f'  "hook": "첫 2초 시선 사로잡는 메시지",\n'
        f'  "scenes": [\n'
        f'    {{"timecode": "0:00-0:05", "visual": "장면 묘사", "voiceover": "내레이션", "on_screen_text": "자막"}}\n'
        f"  ],\n"
        f'  "cta": "콜투액션 한 문장",\n'
        f'  "hashtags": ["#태그1", "#태그2"]\n'
        f"}}\n"
        f"```"
    )


async def generate_video(
    db: AsyncSession,
    *,
    user_id: str,
    plan_code: str | None,
    allowed_models: str,
    req: VideoGenerateRequest,
) -> tuple[ContentJob, dict[str, Any], bool]:
    """영상 대본 생성. ``(job, response_payload, success)`` 반환."""
    strategy = _select_strategy_for_plan(allowed_models, "pipeline")
    job = await _create_job(
        db,
        user_id=user_id,
        action="video",
        title=req.title,
        input_payload=req.model_dump(),
        plan_code=plan_code,
        strategy=strategy.value,
    )

    prompt = _build_video_prompt(req)
    started = time.perf_counter()

    try:
        orch = Orchestrator(
            domain=OntologyDomain.BUSINESS,
            strategy=strategy,
            max_iterations=2,
        )
        res = await orch.execute(prompt)
        raw = str(res.output or "")
        model_used = (
            res.agent_results[-1].model_used
            if res.agent_results
            else None
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        parsed = _extract_json(raw)
        if parsed is None:
            await _finalize_job(
                db, job,
                success=False,
                output_text=raw,
                output_payload=None,
                model_used=model_used,
                latency_ms=latency_ms,
                ontology_passed=False,
                ontology_errors=["LLM 응답에서 JSON 추출 실패"],
                error_message="응답 형식 오류",
            )
            return job, {
                "job_id": job.id,
                "status": "failed",
                "script": None,
                "model_used": model_used,
                "ontology_passed": False,
                "ontology_errors": ["LLM 응답에서 JSON 추출 실패"],
                "latency_ms": latency_ms,
            }, False

        try:
            script = VideoScript.model_validate(
                {
                    "title": parsed.get("title", req.title),
                    "duration_seconds": parsed.get(
                        "duration_seconds", req.duration_seconds
                    ),
                    "hook": parsed.get("hook", ""),
                    "scenes": [
                        VideoScene(
                            timecode=s.get("timecode", ""),
                            visual=s.get("visual", ""),
                            voiceover=s.get("voiceover", ""),
                            on_screen_text=s.get("on_screen_text"),
                        )
                        for s in (parsed.get("scenes") or [])
                    ],
                    "cta": parsed.get("cta"),
                    "hashtags": parsed.get("hashtags") or [],
                }
            )
        except Exception as ve:
            await _finalize_job(
                db, job,
                success=False,
                output_text=raw,
                output_payload=parsed,
                model_used=model_used,
                latency_ms=latency_ms,
                ontology_passed=False,
                ontology_errors=[f"VideoScript 스키마 위반: {ve}"],
                error_message="스키마 검증 실패",
            )
            return job, {
                "job_id": job.id,
                "status": "failed",
                "script": None,
                "model_used": model_used,
                "ontology_passed": False,
                "ontology_errors": [f"스키마 위반: {ve}"],
                "latency_ms": latency_ms,
            }, False

        onto = await OntologyValidator.for_business().validate(
            {
                "contract_id": f"CON-{datetime.now().strftime('%Y%m%d')}",
                "requester_id": user_id or "AI-VIDEO-AGENT",
                "request_date": datetime.now().date().isoformat(),
                "description": (script.hook + " | " + (script.cta or ""))[:4000],
            }
        )
        await _finalize_job(
            db, job,
            success=True,
            output_text=raw,
            output_payload=script.model_dump(),
            model_used=model_used,
            latency_ms=latency_ms,
            ontology_passed=onto.passed,
            ontology_errors=[e.message for e in onto.errors][:12],
        )
        return job, {
            "job_id": job.id,
            "status": "completed",
            "script": script.model_dump(),
            "model_used": model_used,
            "ontology_passed": onto.passed,
            "ontology_errors": [e.message for e in onto.errors][:12],
            "latency_ms": latency_ms,
        }, True

    except Exception as e:
        latency_ms = int((time.perf_counter() - started) * 1000)
        log.exception("video 생성 실패 job=%s", job.id[:8])
        await _finalize_job(
            db, job,
            success=False,
            output_text=None,
            output_payload=None,
            model_used=None,
            latency_ms=latency_ms,
            ontology_passed=None,
            ontology_errors=None,
            error_message=str(e)[:500],
        )
        return job, {
            "job_id": job.id,
            "status": "failed",
            "script": None,
            "model_used": None,
            "ontology_passed": None,
            "ontology_errors": [],
            "latency_ms": latency_ms,
        }, False


# ── SNS Agent ───────────────────────────────────────────────────────


PLATFORM_LIMITS = {
    "twitter": 280,
    "linkedin": 1300,
    "instagram": 2200,
}


def _build_sns_prompt(req: SNSPostRequest) -> str:
    audience = req.audience or "일반 사용자"
    platforms = ", ".join(req.platforms)
    return (
        f"당신은 CoOps SaaS 의 SNS 콘텐츠 작가입니다. "
        f"BUSINESS Ontology 규칙 준수 — 허위/과장 광고, 의료 효능 단정, 비교 광고, PII 금지.\n\n"
        f"주제: {req.topic}\n"
        f"플랫폼: {platforms}\n"
        f"대상: {audience}\n"
        f"톤: {req.tone}\n"
        f"이모지: {'사용 OK' if req.include_emoji else '금지'}\n"
        f"해시태그: {'포함' if req.include_hashtags else '제외'}\n\n"
        f"플랫폼별 길이 제한 (글자):\n"
        f"  - twitter: 280자 이내\n"
        f"  - linkedin: 1300자 이내 (전문성)\n"
        f"  - instagram: 2200자 이내 (감성)\n\n"
        f"다음 JSON 형식만으로 응답:\n"
        f"```json\n"
        f"{{\n"
        f'  "posts": [\n'
        f'    {{"platform": "twitter", "body": "...", "hashtags": ["#a"]}},\n'
        f'    {{"platform": "linkedin", "body": "...", "hashtags": ["#a"]}}\n'
        f"  ]\n"
        f"}}\n"
        f"```"
    )


async def generate_sns_posts(
    db: AsyncSession,
    *,
    user_id: str,
    plan_code: str | None,
    allowed_models: str,
    req: SNSPostRequest,
) -> tuple[ContentJob, dict[str, Any], bool]:
    strategy = _select_strategy_for_plan(allowed_models, "pipeline")
    job = await _create_job(
        db,
        user_id=user_id,
        action="sns",
        title=req.topic[:200],
        input_payload=req.model_dump(),
        plan_code=plan_code,
        strategy=strategy.value,
    )
    prompt = _build_sns_prompt(req)
    started = time.perf_counter()

    try:
        orch = Orchestrator(
            domain=OntologyDomain.BUSINESS,
            strategy=strategy,
            max_iterations=2,
        )
        res = await orch.execute(prompt)
        raw = str(res.output or "")
        model_used = res.agent_results[-1].model_used if res.agent_results else None
        latency_ms = int((time.perf_counter() - started) * 1000)

        parsed = _extract_json(raw)
        posts_raw = (parsed or {}).get("posts") or []
        if not posts_raw:
            await _finalize_job(
                db, job,
                success=False,
                output_text=raw,
                output_payload=parsed,
                model_used=model_used,
                latency_ms=latency_ms,
                ontology_passed=False,
                ontology_errors=["응답에 posts 배열 없음"],
                error_message="응답 형식 오류",
            )
            return job, {
                "job_id": job.id,
                "status": "failed",
                "posts": [],
                "model_used": model_used,
                "ontology_passed": False,
                "ontology_errors": ["응답에 posts 배열 없음"],
                "latency_ms": latency_ms,
            }, False

        outputs: list[SNSPostPlatformOutput] = []
        for p in posts_raw:
            plat = (p.get("platform") or "").lower()
            if plat not in req.platforms:
                continue
            body = (p.get("body") or "").strip()
            limit = PLATFORM_LIMITS.get(plat, 2200)
            if len(body) > limit:
                body = body[: limit - 1] + "…"
            outputs.append(
                SNSPostPlatformOutput(
                    platform=plat,
                    body=body,
                    hashtags=p.get("hashtags") or [],
                    char_count=len(body),
                )
            )

        combined = " | ".join(o.body for o in outputs)
        onto = await OntologyValidator.for_business().validate(
            {
                "contract_id": f"CON-{datetime.now().strftime('%Y%m%d')}",
                "requester_id": user_id or "AI-SNS-AGENT",
                "request_date": datetime.now().date().isoformat(),
                "description": combined[:4000],
            }
        )
        out_payload = {"posts": [o.model_dump() for o in outputs]}
        await _finalize_job(
            db, job,
            success=True,
            output_text=raw,
            output_payload=out_payload,
            model_used=model_used,
            latency_ms=latency_ms,
            ontology_passed=onto.passed,
            ontology_errors=[e.message for e in onto.errors][:12],
        )
        return job, {
            "job_id": job.id,
            "status": "completed",
            "posts": [o.model_dump() for o in outputs],
            "model_used": model_used,
            "ontology_passed": onto.passed,
            "ontology_errors": [e.message for e in onto.errors][:12],
            "latency_ms": latency_ms,
        }, True

    except Exception as e:
        latency_ms = int((time.perf_counter() - started) * 1000)
        log.exception("sns 생성 실패 job=%s", job.id[:8])
        await _finalize_job(
            db, job,
            success=False,
            output_text=None,
            output_payload=None,
            model_used=None,
            latency_ms=latency_ms,
            ontology_passed=None,
            ontology_errors=None,
            error_message=str(e)[:500],
        )
        return job, {
            "job_id": job.id,
            "status": "failed",
            "posts": [],
            "model_used": None,
            "ontology_passed": None,
            "ontology_errors": [],
            "latency_ms": latency_ms,
        }, False


# ── Investor Agent ─────────────────────────────────────────────────


def _build_investor_prompt(req: InvestorReportRequest) -> str:
    metrics = "\n".join(
        f"  - {m.name}: {m.value} ({m.direction or 'flat'}){' — ' + m.note if m.note else ''}"
        for m in req.metrics
    ) or "  - (지표 없음)"
    highlights = "\n".join(f"  - {h}" for h in req.highlights) or "  - (없음)"
    risks = "\n".join(f"  - {r}" for r in req.risks) or "  - (없음)"
    return (
        f"당신은 CoOps SaaS 의 SMB 분기 IR (Investor Relations) 보고서 작성 전문가입니다.\n"
        f"BUSINESS Ontology 규칙 — 미래 수치 단정/투자 권유 금지, PII 금지, 허위 진술 금지.\n\n"
        f"회사: {req.company_name}\n"
        f"분기: {req.quarter}\n"
        f"대상 청중: {req.audience}\n\n"
        f"하이라이트:\n{highlights}\n\n"
        f"정량 지표:\n{metrics}\n\n"
        f"리스크:\n{risks}\n\n"
        f"다음 JSON 형식만으로 응답:\n"
        f"```json\n"
        f"{{\n"
        f'  "executive_summary": "3-5문장 요약",\n'
        f'  "report_markdown": "## 1. 분기 요약\\n...\\n## 2. 정량 지표\\n...\\n## 3. 핵심 성과\\n...\\n## 4. 리스크 및 대응\\n...\\n## 5. 다음 분기 계획\\n...",\n'
        f'  "slides": [\n'
        f'    {{"section": "Highlights", "headline": "...", "bullets": ["...", "..."]}},\n'
        f'    {{"section": "Metrics", "headline": "...", "bullets": ["..."]}}\n'
        f"  ]\n"
        f"}}\n"
        f"```"
    )


async def generate_investor_report(
    db: AsyncSession,
    *,
    user_id: str,
    plan_code: str | None,
    allowed_models: str,
    req: InvestorReportRequest,
) -> tuple[ContentJob, dict[str, Any], bool]:
    """IR 보고서 + 슬라이드 — SMB+ 권장 (HEAVY 모델 필요)."""
    strategy = _select_strategy_for_plan(allowed_models, "debate")
    job = await _create_job(
        db,
        user_id=user_id,
        action="investor",
        title=f"{req.company_name} {req.quarter}",
        input_payload=req.model_dump(),
        plan_code=plan_code,
        strategy=strategy.value,
    )
    prompt = _build_investor_prompt(req)
    started = time.perf_counter()

    try:
        orch = Orchestrator(
            domain=OntologyDomain.BUSINESS,
            strategy=strategy,
            max_iterations=2,
        )
        res = await orch.execute(prompt)
        raw = str(res.output or "")
        model_used = res.agent_results[-1].model_used if res.agent_results else None
        latency_ms = int((time.perf_counter() - started) * 1000)

        parsed = _extract_json(raw)
        if parsed is None:
            await _finalize_job(
                db, job,
                success=False,
                output_text=raw,
                output_payload=None,
                model_used=model_used,
                latency_ms=latency_ms,
                ontology_passed=False,
                ontology_errors=["JSON 추출 실패"],
                error_message="응답 형식 오류",
            )
            return job, {
                "job_id": job.id,
                "status": "failed",
                "report": None,
                "model_used": model_used,
                "ontology_passed": False,
                "ontology_errors": ["JSON 추출 실패"],
                "latency_ms": latency_ms,
            }, False

        try:
            report = InvestorReport(
                company_name=req.company_name,
                quarter=req.quarter,
                executive_summary=parsed.get("executive_summary") or "",
                report_markdown=parsed.get("report_markdown") or "",
                slides=[
                    InvestorSlide(
                        section=s.get("section", ""),
                        headline=s.get("headline", ""),
                        bullets=s.get("bullets") or [],
                    )
                    for s in (parsed.get("slides") or [])
                ],
            )
        except Exception as ve:
            await _finalize_job(
                db, job,
                success=False,
                output_text=raw,
                output_payload=parsed,
                model_used=model_used,
                latency_ms=latency_ms,
                ontology_passed=False,
                ontology_errors=[f"InvestorReport 스키마 위반: {ve}"],
                error_message="스키마 검증 실패",
            )
            return job, {
                "job_id": job.id,
                "status": "failed",
                "report": None,
                "model_used": model_used,
                "ontology_passed": False,
                "ontology_errors": [f"스키마 위반: {ve}"],
                "latency_ms": latency_ms,
            }, False

        onto = await OntologyValidator.for_business().validate(
            {
                "contract_id": f"CON-{datetime.now().strftime('%Y%m%d')}",
                "requester_id": user_id or "AI-INVESTOR-AGENT",
                "request_date": datetime.now().date().isoformat(),
                "description": report.executive_summary[:4000],
            }
        )
        await _finalize_job(
            db, job,
            success=True,
            output_text=raw,
            output_payload=report.model_dump(),
            model_used=model_used,
            latency_ms=latency_ms,
            ontology_passed=onto.passed,
            ontology_errors=[e.message for e in onto.errors][:12],
        )
        return job, {
            "job_id": job.id,
            "status": "completed",
            "report": report.model_dump(),
            "model_used": model_used,
            "ontology_passed": onto.passed,
            "ontology_errors": [e.message for e in onto.errors][:12],
            "latency_ms": latency_ms,
        }, True

    except Exception as e:
        latency_ms = int((time.perf_counter() - started) * 1000)
        log.exception("investor 생성 실패 job=%s", job.id[:8])
        await _finalize_job(
            db, job,
            success=False,
            output_text=None,
            output_payload=None,
            model_used=None,
            latency_ms=latency_ms,
            ontology_passed=None,
            ontology_errors=None,
            error_message=str(e)[:500],
        )
        return job, {
            "job_id": job.id,
            "status": "failed",
            "report": None,
            "model_used": None,
            "ontology_passed": None,
            "ontology_errors": [],
            "latency_ms": latency_ms,
        }, False


__all__ = [
    "generate_video",
    "generate_sns_posts",
    "generate_investor_report",
]
