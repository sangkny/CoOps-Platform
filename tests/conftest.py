"""pytest — ASGITransport + async 엔진 풀 정리."""
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from database import engine
from main import app


@pytest_asyncio.fixture(autouse=True)
async def _dispose_async_engine() -> AsyncIterator[None]:
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
