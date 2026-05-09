"""헬스 — GET /health (Docker 헬스체크용)."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings, get_settings
from database import get_db
from schemas.business import HealthResponse

log = logging.getLogger("api.health")
router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="서비스·DB 상태")
async def health(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    ok = False
    try:
        await db.execute(text("SELECT 1"))
        ok = True
    except Exception as exc:
        log.warning("DB 체크 실패: %s", exc)

    return HealthResponse(
        status="ok" if ok else "degraded",
        service=settings.service_name,
        version=settings.version,
        db_connected=ok,
        timestamp=datetime.now(timezone.utc),
    )
