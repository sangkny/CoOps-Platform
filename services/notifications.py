"""CoOps NotificationService 인스턴스 — shared.notifications 위임 (E-Day 4 / E-R2-Day 1).

E-R2-Day 1 에서 ``InboxService`` 가 추가되어 push 발송과 동시에 ``coops_notifications``
테이블에 in-app 알림이 영속화된다.
"""
from __future__ import annotations

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

__all__ = ["coops_push_config", "coops_inbox", "coops_notifier"]
