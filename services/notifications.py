"""CoOps NotificationService 인스턴스 — shared.notifications 위임 (E-Day 4)."""
from __future__ import annotations

from models.notifications import PushDevice
from notifications import NotificationService, PushConfig

coops_push_config = PushConfig.from_env(prefix="COOPS")
coops_notifier = NotificationService(
    config=coops_push_config,
    device_cls=PushDevice,
    service_name="coops",
)

__all__ = ["coops_push_config", "coops_notifier"]
