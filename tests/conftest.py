from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy import text

from app.db import AsyncSessionLocal, engine, get_db
from app.main import app
from app.quota.service import configure_quota


@pytest_asyncio.fixture(autouse=True)
async def dispose_connections():
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def api_client() -> AsyncIterator[tuple[httpx.AsyncClient, object]]:
    db = object()

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, db

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def quota_factory() -> AsyncIterator[
    Callable[[int], Awaitable[tuple[UUID, str]]]
]:
    org_ids: list[UUID] = []

    async def create(limit_units: int) -> tuple[UUID, str]:
        org_id = uuid4()
        feature = "test-feature"
        org_ids.append(org_id)

        async with AsyncSessionLocal() as db:
            await configure_quota(db, org_id, feature, limit_units)

        return org_id, feature

    yield create

    async with AsyncSessionLocal() as db:
        async with db.begin():
            for org_id in org_ids:
                await db.execute(
                    text("DELETE FROM quota_reservations WHERE org_id = :org_id"),
                    {"org_id": org_id},
                )
                await db.execute(
                    text("DELETE FROM quota_counters WHERE org_id = :org_id"),
                    {"org_id": org_id},
                )
                await db.execute(
                    text("DELETE FROM quota_limits WHERE org_id = :org_id"),
                    {"org_id": org_id},
                )
