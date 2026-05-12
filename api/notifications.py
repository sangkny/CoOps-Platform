"""CoOps push notification 라우트 (E-Day 4, 2026-05-13).

엔드포인트:
    POST   /api/v1/notifications/devices                — 본인 단말 등록 (idempotent)
    DELETE /api/v1/notifications/devices/{token}        — 본인 단말 폐기
    GET    /api/v1/notifications/devices                — 본인 활성 단말 목록
    POST   /api/v1/notifications/admin/send-test        — admin — 임의 user 에 푸시 발송

설계:
    - shared.notifications.NotificationService 위임. CoOps 의 prefix `coops_`.
    - PUSH_ENABLED=0 기본. 등록/조회/폐기 라우트는 토글과 무관 (DB 만 사용).
      발송만 ``PushDisabledError`` 에서 503.
    - 인증/RBAC: 등록·조회·폐기는 인증된 모든 사용자, send-test 는 admin 전용.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import current_user_strict, require_role
from database import get_db
from notifications import PushDisabledError
from schemas.notifications import (
    DeviceListResponse,
    DeviceOut,
    DeviceRegisterRequest,
    SendResult,
    SendTestRequest,
)
from services.notifications import coops_notifier, coops_push_config

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
