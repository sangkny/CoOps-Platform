"""CoOps 콘텐츠 생성 요청/응답 스키마 (Phase 2 → C Week 2)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Video ────────────────────────────────────────────────────────────


class VideoGenerateRequest(BaseModel):
    """영상 대본 생성 요청.

    ``duration_seconds`` 는 15 (틱톡/숏폼), 60 (인스타 릴스), 180 (유튜브 쇼츠/광고)
    중 택일. 자유 입력은 백로그.
    """

    title: str = Field(..., min_length=2, max_length=200)
    topic: str = Field(..., min_length=4, max_length=2000)
    duration_seconds: Literal[15, 60, 180] = 60
    audience: str | None = Field(default=None, max_length=200)
    tone: Literal["informative", "energetic", "trustworthy", "playful"] = "trustworthy"
    cta: str | None = Field(default=None, max_length=200, description="콜투액션 (예: '지금 방문')")


class VideoScene(BaseModel):
    """영상 한 장면."""

    timecode: str = Field(..., description="예: 0:00-0:05")
    visual: str
    voiceover: str
    on_screen_text: str | None = None


class VideoScript(BaseModel):
    title: str
    duration_seconds: int
    hook: str
    scenes: list[VideoScene]
    cta: str | None = None
    hashtags: list[str] = Field(default_factory=list)


class VideoGenerateResponse(BaseModel):
    job_id: str
    status: str
    script: VideoScript | None = None
    model_used: str | None = None
    ontology_passed: bool | None = None
    ontology_errors: list[str] = Field(default_factory=list)
    latency_ms: int | None = None


# ── SNS ──────────────────────────────────────────────────────────────


class SNSPostRequest(BaseModel):
    """SNS 본문 생성 요청 — 플랫폼별 길이/스타일이 다르다."""

    topic: str = Field(..., min_length=4, max_length=2000)
    platforms: list[Literal["twitter", "linkedin", "instagram"]] = Field(
        ..., min_length=1
    )
    tone: Literal["casual", "professional", "inspiring"] = "professional"
    audience: str | None = Field(default=None, max_length=200)
    include_hashtags: bool = True
    include_emoji: bool = True


class SNSPostPlatformOutput(BaseModel):
    platform: str
    body: str = Field(..., description="플랫폼별 본문 (길이 자동 조정)")
    hashtags: list[str] = Field(default_factory=list)
    char_count: int = 0


class SNSPostResponse(BaseModel):
    job_id: str
    status: str
    posts: list[SNSPostPlatformOutput] = Field(default_factory=list)
    model_used: str | None = None
    ontology_passed: bool | None = None
    ontology_errors: list[str] = Field(default_factory=list)
    latency_ms: int | None = None


# ── Investor ────────────────────────────────────────────────────────


class InvestorMetric(BaseModel):
    """IR 보고서에 첨부할 정량 지표."""

    name: str = Field(..., min_length=1, max_length=64)
    value: str = Field(..., min_length=1, max_length=128)
    direction: Literal["up", "down", "flat"] | None = None
    note: str | None = None


class InvestorReportRequest(BaseModel):
    """분기 보고서 + IR 슬라이드 생성 요청."""

    company_name: str = Field(..., min_length=1, max_length=200)
    quarter: str = Field(..., pattern=r"^\d{4}Q[1-4]$", description="예: 2026Q2")
    highlights: list[str] = Field(default_factory=list, max_length=10)
    metrics: list[InvestorMetric] = Field(default_factory=list, max_length=15)
    risks: list[str] = Field(default_factory=list, max_length=10)
    audience: Literal["board", "vc", "internal"] = "vc"


class InvestorSlide(BaseModel):
    section: str
    headline: str
    bullets: list[str] = Field(default_factory=list)


class InvestorReport(BaseModel):
    company_name: str
    quarter: str
    executive_summary: str
    report_markdown: str
    slides: list[InvestorSlide] = Field(default_factory=list)


class InvestorReportResponse(BaseModel):
    job_id: str
    status: str
    report: InvestorReport | None = None
    model_used: str | None = None
    ontology_passed: bool | None = None
    ontology_errors: list[str] = Field(default_factory=list)
    latency_ms: int | None = None


# ── 공통 ContentJob 조회 ────────────────────────────────────────────


class ContentJobOut(BaseModel):
    """``GET /content/jobs/{id}`` — 본인 콘텐츠 작업 단건 조회."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    action: str
    title: str | None
    status: str
    plan_code: str | None
    model_used: str | None
    strategy: str | None
    tokens_estimated: int
    latency_ms: int | None
    ontology_passed: bool | None
    ontology_errors: list[str] = Field(default_factory=list)
    output_text: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class ContentJobListResponse(BaseModel):
    user_id: str
    jobs: list[ContentJobOut]
    total: int
