"""CoOps push device + inbox ORM (E-Day 4 / E-R2-Day 1).

- ``PushDevice`` (E-Day 4) — ``coops_push_devices``.
- ``Notification`` (E-R2-Day 1) — ``coops_notifications`` (in-app inbox).
"""
from __future__ import annotations

from database import Base
from notifications import make_inbox_models, make_notification_models

PushDevice = make_notification_models(Base, table_prefix="coops_")
Notification = make_inbox_models(Base, table_prefix="coops_")

__all__ = ["PushDevice", "Notification"]
