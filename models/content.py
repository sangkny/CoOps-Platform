"""CoOps 콘텐츠 생성 ORM (Phase 2 → C Week 2, 2026-05-13).

3종 콘텐츠 (Video / SNS / Investor) 가 공통 워크플로 (request → LLM 호출 →
output 저장) 를 가지므로 **통합 ``ContentJob`` 단일 테이블** 로 시작한다.
``action`` 으로 종류 구분, ``input_json`` / ``output_json`` 으로 스키마 차이 흡수.

향후 라이프사이클이 분기되면 (예: Video 에 음성 더빙 파일, SNS 에 게시
스케줄링, Investor 에 PDF 첨부) 별도 1-to-1 sidecar 테이블로 확장.

테스트 철학: BUSINESS Ontology 검증 + Quota 차단은 라우트 deps 가 처리하므로
ORM 자체에는 비즈니스 규칙이 들어가지 않는다.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ContentJob(Base):
    """통합 콘텐츠 생성 작업.

    Action 값:
        - ``video`` — 영상 대본 (15/60/180초)
        - ``sns`` — 플랫폼별 SNS 포스트 (twitter/linkedin/instagram)
        - ``investor`` — 분기 보고서 / IR 슬라이드 markdown

    상태 머신: ``pending → running → completed | failed``.
    """

    __tablename__ = "coops_content_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)

    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
    tokens_estimated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    ontology_passed: Mapped[bool | None] = mapped_column(nullable=True)
    ontology_errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = ["ContentJob"]
