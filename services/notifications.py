"""CoOps NotificationService 인스턴스 — shared.notifications 위임 (E-Day 4 / E-R2-Day 1 / E-R3-Day 1).

E-R2-Day 1 에서 ``InboxService`` 가 추가되어 push 발송과 동시에 ``coops_notifications``
테이블에 in-app 알림이 영속화된다. E-R3-Day 1 에서 ``_notify_safe`` best-effort
헬퍼가 공통 모듈로 이동 (approvals + content 라우트가 공유).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.notifications import Notification, PushDevice
from notifications import InboxService, NotificationService, PushConfig

coops_push_config = PushConfig.from_env(prefix="COOPS")
coops_inbox = InboxService(notification_cls=Notification, service_name="coops")
coops_notifier = NotificationService(
    config=coops_push_config,
    device_cls=PushDevice,
    service_name="coops",
    inbox=coops_inbox,
)

log = logging.getLogger(__name__)


async def notify_safe(
    db: AsyncSession,
    *,
    user_id: str | None,
    kind: str,
    title: str,
    body: str,
    ref_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Best-effort 알림 — inbox + push 양쪽 실패해도 트랜잭션을 막지 않는다.

    - ``user_id`` 가 비었으면 noop.
    - 호출 시점은 ``await db.flush()`` 이후가 안전 (ref_id 가 ORM id 를 가리킴).
    """
    if not user_id:
        return
    try:
        await coops_notifier.notify(
            db,
            user_id=user_id,
            title=title,
            body=body,
            kind=kind,
            ref_id=ref_id,
            data=data,
        )
    except Exception as exc:  # pragma: no cover - best-effort
        log.warning(
            "notify_safe_failed kind=%s user=%s ref=%s err=%s",
            kind, user_id, ref_id, exc,
        )


__all__ = ["coops_push_config", "coops_inbox", "coops_notifier", "notify_safe"]
