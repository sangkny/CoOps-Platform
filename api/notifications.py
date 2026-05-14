"""CoOps push notification 라우트 (E-Day 4 / E-R2-Day 1).

엔드포인트:
    POST   /api/v1/notifications/devices                — 본인 단말 등록 (idempotent)
    DELETE /api/v1/notifications/devices/{token}        — 본인 단말 폐기
    GET    /api/v1/notifications/devices                — 본인 활성 단말 목록
    POST   /api/v1/notifications/admin/send-test        — admin — 임의 user 에 푸시 발송
    GET    /api/v1/notifications/inbox                  — in-app 알림 목록 (E-R2)
    PATCH  /api/v1/notifications/inbox/{id}/read        — 단건 읽음 처리 (E-R2)
    POST   /api/v1/notifications/inbox/read-all         — 일괄 읽음 처리 (E-R2)

설계:
    - shared.notifications.NotificationService + InboxService 위임.
    - PUSH_ENABLED=0 기본. 등록/조회/폐기/inbox 라우트는 토글과 무관 (DB 만 사용).
      발송만 ``PushDisabledError`` 에서 503.
    - 인증/RBAC: 등록·조회·폐기·inbox 는 인증된 모든 사용자, send-test 는 admin 전용.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import current_user_strict, require_role
from database import get_db
from notifications import PushDisabledError
from schemas.notifications import (
    DeviceListResponse,
    DeviceOut,
    DeviceRegisterRequest,
    InboxItemOut,
    InboxListResponse,
    MarkReadAllResult,
    SendResult,
    SendTestRequest,
)
from services.notifications import coops_inbox, coops_notifier, coops_push_config

router = APIRouter()


def _to_out(row) -> DeviceOut:
    return DeviceOut(
        id=row.id,
        user_id=row.user_id,
        expo_push_token=row.expo_push_token,
        platform=row.platform,
        device_label=row.device_label,
        active=row.active,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
    )


@router.post(
    "/devices",
    response_model=DeviceOut,
    summary="단말 등록 (idempotent — 동일 token 은 갱신)",
)
async def register_device(
    body: DeviceRegisterRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
) -> DeviceOut:
    row = await coops_notifier.register_device(
        db,
        user_id=user["user_id"],
        expo_push_token=body.expo_push_token,
        platform=body.platform,
        device_label=body.device_label,
    )
    await db.commit()
    return _to_out(row)


@router.delete(
    "/devices/{expo_push_token}",
    summary="단말 폐기 (soft delete)",
)
async def unregister_device(
    expo_push_token: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(current_user_strict),
) -> dict:
    ok = await coops_notifier.revoke_device(db, expo_push_token=expo_push_token)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="device_not_found",
        )
    await db.commit()
    return {"ok": True}


@router.get(
    "/devices",
    response_model=DeviceListResponse,
    summary="본인 활성 단말 목록",
)
async def list_devices(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
) -> DeviceListResponse:
    rows = await coops_notifier.list_active_for_user(db, user_id=user["user_id"])
    return DeviceListResponse(
        user_id=user["user_id"],
        devices=[_to_out(r) for r in rows],
    )


@router.post(
    "/admin/send-test",
    response_model=SendResult,
    summary="admin — 임의 user 에게 푸시 발송 (개발/검증)",
)
async def admin_send_test(
    body: SendTestRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_role("admin")),
) -> SendResult:
    try:
        result = await coops_notifier.send_to_user(
            db,
            user_id=body.user_id,
            title=body.title,
            body=body.body,
            data=body.data,
        )
    except PushDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return SendResult(**result)


# ── In-app inbox (E-R2-Day 1) ────────────────────────────────────────


def _inbox_to_out(row) -> InboxItemOut:
    parsed: dict | None = None
    if row.data_json:
        try:
            parsed = json.loads(row.data_json)
        except (ValueError, TypeError):
            parsed = {"_raw": row.data_json}
    return InboxItemOut(
        id=row.id,
        user_id=row.user_id,
        kind=row.kind,
        title=row.title,
        body=row.body,
        ref_id=row.ref_id,
        data=parsed,
        read=row.read,
        read_at=row.read_at,
        created_at=row.created_at,
    )


@router.get(
    "/inbox",
    response_model=InboxListResponse,
    summary="본인 in-app 알림 목록",
)
async def list_inbox(
    unread_only: bool = Query(False, description="true 면 미읽음만 반환"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
) -> InboxListResponse:
    rows = await coops_inbox.list_for_user(
        db,
        user_id=user["user_id"],
        unread_only=unread_only,
        limit=limit,
    )
    unread = await coops_inbox.unread_count(db, user_id=user["user_id"])
    return InboxListResponse(
        user_id=user["user_id"],
        unread_count=unread,
        items=[_inbox_to_out(r) for r in rows],
    )


@router.patch(
    "/inbox/{notification_id}/read",
    summary="단건 읽음 처리",
)
async def mark_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
) -> dict:
    ok = await coops_inbox.mark_read(
        db, notification_id=notification_id, user_id=user["user_id"]
    )
    await db.commit()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="notification_not_found_or_already_read",
        )
    return {"ok": True}


@router.post(
    "/inbox/read-all",
    response_model=MarkReadAllResult,
    summary="본인 모든 미읽음 알림 일괄 읽음 처리",
)
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
) -> MarkReadAllResult:
    updated = await coops_inbox.mark_all_read(db, user_id=user["user_id"])
    await db.commit()
    return MarkReadAllResult(updated=updated)


# ── Inbox retention (E R3-Day 4) ─────────────────────────────────────


@router.post(
    "/admin/purge-old",
    summary="admin — 오래된 in-app 알림 일괄 삭제 (retention)",
)
async def admin_purge_old(
    days: int = Query(
        default=90, ge=0, le=3650,
        description="이 일수보다 오래된 알림 삭제",
    ),
    include_unread: bool = Query(
        default=False,
        description="true 면 미독 알림도 함께 삭제 (위험: 사용자가 못본 알림 손실)",
    ),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_role("admin")),
) -> dict:
    """수동 retention 정리. 자동 스케줄러는 ``INBOX_RETENTION_ENABLED=1`` 환경에서
    매 ``INBOX_RETENTION_INTERVAL_HOURS`` (기본 24) 시간 마다 동일 정리를 수행한다.
    """
    deleted = await coops_inbox.purge_older_than(
        db, days=days, include_unread=include_unread,
    )
    await db.commit()
    return {
        "deleted": deleted,
        "days": days,
        "include_unread": include_unread,
    }
