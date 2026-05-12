"""pytest — ASGITransport + async 엔진 풀 정리 + SaaS 쿼터 격리.

기존 결재 테스트가 새 SaaS 쿼터 (Phase 2 → C-5) 에 영향받지 않도록, 매 테스트
시작 전 ``staff``/``manager`` 사용자를 무제한 ``ent`` plan 으로 강제 + 당월
사용량을 0 으로 리셋한다 (ADK 의 ``_reset_user_to_ent_unlimited`` 와 동등).

테스트 철학 (2026-05-12):
    - LLM/네트워크 mock 없음 — 실제 DB 만 조작
    - 격리: 매 테스트마다 동일 시작 상태 보장
"""
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from database import async_session_maker, engine
from main import app
from models.billing import BillingMonthlyUserUsage, BillingSubscription
from saas.helpers import current_year_month
from services.billing import coops_billing


async def _reset_user_to_ent(user_id: str) -> None:
    """``user_id`` 를 무제한 ent plan 으로 + 당월 calls_count=0 으로 강제."""
    async with async_session_maker() as session:
        ent = await coops_billing.get_plan_by_code(session, "ent")
        if ent is None:
            return
        await session.execute(
            update(BillingSubscription)
            .where(BillingSubscription.user_id == user_id)
            .where(BillingSubscription.status == "active")
            .values(status="cancelled")
        )
        sub, _plan = await coops_billing.get_or_create_active_subscription(
            session, user_id
        )
        if sub.plan_id != ent.id:
            sub.plan_id = ent.id
            sub.status = "active"
        ym = current_year_month()
        monthly = await coops_billing.get_or_create_monthly_usage(
            session, user_id, year_month=ym
        )
        monthly.calls_count = 0
        monthly.tokens_total = 0
        await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _saas_quota_isolation() -> AsyncIterator[None]:
    """staff/manager 사용자를 무제한 plan + 사용량 0 으로 초기화."""
    for uid in ("staff", "manager"):
        await _reset_user_to_ent(uid)
    yield


@pytest_asyncio.fixture(autouse=True)
async def _dispose_async_engine() -> AsyncIterator[None]:
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
