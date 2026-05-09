"""
CoOps Platform — 비즈니스 프로세스·계약 (BUSINESS 도메인 연계 예정).

shared-libraries 는 `PYTHONPATH` 로 로드 (-- docker-compose 마운트).
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI

from api import api_router
from config import Settings, get_settings
from database import create_tables

log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await create_tables()
    settings = get_settings()
    log.info("%s v%s 시작 (테이블: create_tables)", settings.service_name, settings.version)
    yield
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
