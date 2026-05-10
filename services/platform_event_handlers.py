"""Week 6 — Redis 플랫폼 이벤트 구독 (CoOps 측)."""
from __future__ import annotations

import logging
from typing import Any

from events.constants import EVENT_MEDICAL_DIAGNOSIS_COMPLETED

log = logging.getLogger("services.platform_event_handlers")


async def coops_incoming_dispatch(event_type: str, data: dict[str, Any]) -> None:
    """MEDI-IOT `medical.diagnosis.completed` → 청구 초안 생성 등(플레이스홀더)."""
    if event_type != EVENT_MEDICAL_DIAGNOSIS_COMPLETED:
        return
    dx = str(data.get("diagnosis_id", "") or "")
    exam = str(data.get("exam_id", "") or "")
    log.info(
        "[CoOps] 진단 완료 이벤트 → 청구 자동 생성(예정) diagnosis=%s exam=%s",
        dx[:16] if dx else "?",
        exam[:16] if exam else "?",
    )
