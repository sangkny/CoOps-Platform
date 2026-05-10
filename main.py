"""
CoOps Platform — 비즈니스 프로세스·계약 (BUSINESS 도메인 연계 예정).

shared-libraries 는 `PYTHONPATH` 로 로드 (-- docker-compose 마운트).
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI

from api import api_router
from config import Settings, get_settings
from events import DEFAULT_EVENTS_CHANNEL, EventBus
from services.platform_event_handlers import coops_incoming_dispatch

log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    log.info(
        "%s v%s 시작 (스키마: 컨테이너 시작 시 alembic upgrade head)",
        settings.service_name,
        settings.version,
    )

    subscriber_stop = asyncio.Event()
    redis_url = (settings.redis_url or "").strip()

    async def run_event_subscriber() -> None:
        await EventBus(redis_url).subscribe(
            DEFAULT_EVENTS_CHANNEL,
            coops_incoming_dispatch,
            stop_event=subscriber_stop,
        )

    sub_task: asyncio.Task[None] | None = None
    if redis_url:
        sub_task = asyncio.create_task(
            run_event_subscriber(),
            name="coops-platform-events-sub",
        )
        log.info("Redis 이벤트 구독: channel=%s", DEFAULT_EVENTS_CHANNEL)
    else:
        log.warning("redis_url 미설정 — 플랫폼 간 이벤트 구독 생략")

    yield

    subscriber_stop.set()
    if sub_task and not sub_task.done():
        try:
            await asyncio.wait_for(sub_task, timeout=5.0)
        except asyncio.TimeoutError:
            sub_task.cancel()
        except Exception:
            log.exception("이벤트 구독 태스크 종료 오류")

    log.info("%s 종료", settings.service_name)


app = FastAPI(
    title="CoOps Platform",
    description="업무 계약·결재·프로세스 자동화 (Week 5 Day 3)",
    version=get_settings().version,
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api/v1")


from api.health import router as health_router  # noqa: E402

app.include_router(
    health_router,
    tags=["health"],
)


@app.get("/")
async def root(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {"service": settings.service_name, "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
