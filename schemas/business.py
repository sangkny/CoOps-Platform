"""Pydantic 스키마 — 계약(CON-YYYYMMDD)·결재·프로세스."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


_CON_NUMBER_RE = re.compile(r"^CON-\d{8}$")


class ContractLifecycle(str, Enum):
    draft              = "draft"
    pending_approval = "pending_approval"
    active             = "active"
    terminated         = "terminated"




class ProcessState(str, Enum):
    idle      = "idle"
    running   = "running"
    completed = "completed"
    failed    = "failed"


def validate_contract_number_format(value: str) -> str:
    """
    계약 번호 형식 CON-YYYYMMDD (대소문자 무시 후 CON 대문자로 정규화).
    예: con-20260509 → CON-20260509
    """
    raw = value.strip().upper()
    if not _CON_NUMBER_RE.fullmatch(raw):
        raise ValueError(
            "계약 번호는 CON-YYYYMMDD 형식이어야 합니다 (예: CON-20260509)",
        )
    digits = raw[4:12]
    # YYYYMMDD 자리만 대략적 달력 검증
    try:
        datetime.strptime(digits, "%Y%m%d")
    except ValueError as e:
        raise ValueError("YYYYMMDD 가 유효한 날짜가 아닙니다.") from e
    return raw


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    db_connected: bool
    timestamp: datetime


class ContractCreate(BaseModel):
    contract_number: str = Field(
        ...,
        examples=["CON-20260509"],
        description="CON-YYYYMMDD",
    )
    title:             str           = Field(min_length=1, max_length=300)
    party_a:           str           = ""
    party_b:           str           = ""
    body_text:         str | None    = None
    effective_date:    date | None   = None
    status:            ContractLifecycle = ContractLifecycle.draft

    @field_validator("contract_number", mode="before")
    @classmethod
    def _co_num(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise TypeError("contract_number 는 문자열이어야 합니다.")
        return validate_contract_number_format(v)


class ContractResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:               str
    contract_number:  str
    title:            str
    party_a:          str
    party_b:          str
    body_text:        str | None
    effective_date:   date | None
    status:           str
    created_at:       datetime


class ApprovalRequestBody(BaseModel):
    """POST /approvals/request — BUSINESS Ontology 검증 대상 dict 조립용."""

    contract_number:       str = Field(description="CON-YYYYMMDD (계약 번호)")
    assigned_approver_id:  str = Field(min_length=1, max_length=128, description="결재 담당 승인자 ID")
    requester_id:          str = Field(min_length=1, max_length=128)
    request_date:          date
    description:           str = Field(default="", max_length=8000)
    amount:                Decimal | None = Field(default=None, description="금액 — 있으면 currency 필수 (Ontology)")
    currency:              str | None = Field(default=None, max_length=8)
    step_order:            int          = Field(default=1, ge=1)
    approver_role:         str          = Field(default="reviewer", max_length=120)

    @field_validator("contract_number", mode="before")
    @classmethod
    def _cn(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise TypeError("contract_number 는 문자열")
        return validate_contract_number_format(v)


class ApprovalApproveBody(BaseModel):
    approver_id: str = Field(min_length=1, max_length=128, description="승인 처리자 ID")


class ApprovalRejectBody(BaseModel):
    approver_id: str = Field(min_length=1, max_length=128)
    reason:      str = Field(min_length=1, max_length=4000)


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:                    str
    contract_id:           str
    step_order:            int
    approver_role:         str
    assigned_approver_id:  str
    requester_id:          str
    request_date:          date
    description:           str | None
    amount:                Decimal | None
    currency:              str | None
    actor_id:              str | None
    status:                str
    comment:               str | None
    finalized:             bool
    created_at:            datetime
    updated_at:            datetime


class ProcessCreate(BaseModel):
    name:          str               = Field(min_length=1, max_length=200)
    description:   str | None        = Field(default=None, max_length=4000)
    workflow_json: str | None       = Field(default=None, description="JSON 문자열 스텝 정의")
    contract_id:   str | None        = None


class ProcessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:             str
    name:           str
    description:    str | None
    workflow_json:  str | None
    status:         str
    contract_id:    str | None
    created_at:     datetime

class ContractAnalyzeBody(BaseModel):
    contract_number: str = Field(
        ...,
        examples=["CON-20260509"],
        description="CON-YYYYMMDD",
    )
    contract_text: str = Field(default="", description="본문 분석 문자열")

    @field_validator("contract_number", mode="before")
    @classmethod
    def _cn_analyze(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise TypeError("contract_number 는 문자열")
        return validate_contract_number_format(v)


class ContractAnalyzeResponse(BaseModel):
    contract_number:        str
    summary:                  str
    risk_level:               str
    risk_highlights:          list[str]
    debate_output_excerpt:   str
    ontology_passed:          bool
    ontology_errors:          list[str]
    lore:                     list[dict[str, Any]] = Field(default_factory=list)
    record_id:                str
