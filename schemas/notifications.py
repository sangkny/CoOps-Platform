"""CoOps notification schemas — 디바이스 등록 + 푸시 발송 응답."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DeviceRegisterRequest(BaseModel):
    expo_push_token: str = Field(..., min_length=10, max_length=256)
    platform: Literal["ios", "android", "web"] = "android"
    device_label: str | None = Field(None, max_length=128)


class DeviceOut(BaseModel):
    id: str
    user_id: str
    expo_push_token: str
    platform: str
    device_label: str | None = None
    active: bool
    created_at: datetime
    last_seen_at: datetime


class DeviceListResponse(BaseModel):
    user_id: str
    devices: list[DeviceOut]


class SendTestRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=400)
    data: dict[str, str] | None = None


class SendResult(BaseModel):
    sent: int
    failed: int
    skipped: int
    tokens: list[str]


# ── In-app inbox (E-R2-Day 1) ────────────────────────────────────────


class InboxItemOut(BaseModel):
    id: str
    user_id: str
    kind: str
    title: str
    body: str
    ref_id: str | None = None
    data: dict | None = None
    read: bool
    read_at: datetime | None = None
    created_at: datetime


class InboxListResponse(BaseModel):
    user_id: str
    unread_count: int
    items: list[InboxItemOut]


class MarkReadAllResult(BaseModel):
    updated: int


class NotifyResult(BaseModel):
    """``notify()`` helper 응답 — inbox 와 push 두 결과를 함께 노출."""

    inbox_id: str | None = None
    push: SendResult | dict
