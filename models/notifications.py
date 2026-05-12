"""CoOps push device ORM — shared.notifications.make_notification_models 위임 (E-Day 4)."""
from __future__ import annotations

from database import Base
from notifications import make_notification_models

PushDevice = make_notification_models(Base, table_prefix="coops_")

__all__ = ["PushDevice"]
