"""CoOps 도메인 ORM — 계약·결재·업무 프로세스."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Contract(Base):
    __tablename__ = "coops_contracts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    contract_number: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    party_a: Mapped[str] = mapped_column(String(200), default="")
    party_b: Mapped[str] = mapped_column(String(200), default="")
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    approvals: Mapped[list["Approval"]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
    )
    processes: Mapped[list["Process"]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
    )


class Approval(Base):
    """결재건 — BUSINESS Ontology + Lore."""

    __tablename__ = "coops_approvals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    contract_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("coops_contracts.id", ondelete="CASCADE"), index=True,
    )
    step_order: Mapped[int] = mapped_column(Integer, default=1)
    approver_role: Mapped[str] = mapped_column(String(120), default="reviewer")

    assigned_approver_id: Mapped[str] = mapped_column(
        String(128), nullable=False,
        comment="결재를 수행해야 할 승인자 ID",
    )
    requester_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)

    actor_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="실제 승인/반려 처리자",
    )

    status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    finalized: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    contract: Mapped["Contract"] = relationship(back_populates="approvals")
    lore_entries: Mapped[list["ApprovalLore"]] = relationship(
        back_populates="approval",
        cascade="all, delete-orphan",
    )


class ApprovalLore(Base):
    """결재 이벤트 Lore (요청·승인·반려 이력)."""

    __tablename__ = "coops_approval_lore"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    approval_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("coops_approvals.id", ondelete="CASCADE"), index=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    approval: Mapped["Approval"] = relationship(back_populates="lore_entries")


class Process(Base):
    """업무 프로세스 실행 단위 (계약 선택적 연결)."""

    __tablename__ = "coops_processes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="idle")
    contract_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("coops_contracts.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    contract: Mapped["Contract | None"] = relationship(
        back_populates="processes",
    )


class ContractAnalysisRecord(Base):
    """계약 DEBATE 분석 결과 (Lore JSON 포함)."""

    __tablename__ = "coops_contract_analyses"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    contract_number: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    debate_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    ontology_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    ontology_errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    lore_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
