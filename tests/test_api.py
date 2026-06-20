from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from app.api import admin_routes, consumer_routes, quota_routes


ORG_ID = UUID("00000000-0000-0000-0000-000000000001")
FEATURE = "test-feature"


async def test_configure_quota(api_client) -> None:
    client, db = api_client
    configured = {
        "org_id": ORG_ID,
        "feature": FEATURE,
        "limit_units": 100,
    }

    with patch.object(
        admin_routes.service,
        "configure_quota",
        AsyncMock(return_value=configured),
    ) as configure:
        response = await client.put(
            f"/admin/orgs/{ORG_ID}/features/{FEATURE}/quota",
            json={"limit_units": 100},
        )

    assert response.status_code == 200
    assert response.json() == {
        "org_id": str(ORG_ID),
        "feature": FEATURE,
        "limit_units": 100,
    }
    configure.assert_awaited_once_with(db, ORG_ID, FEATURE, 100)


async def test_usage_response(api_client) -> None:
    client, _ = api_client
    reset = datetime(2026, 7, 1, tzinfo=UTC)

    with patch.object(
        quota_routes.service,
        "get_feature_usage",
        AsyncMock(
            return_value={
                "used_units": 12,
                "available_units": 88,
                "next_reset_at": reset,
            }
        ),
    ):
        response = await client.get(f"/quota/orgs/{ORG_ID}/features/{FEATURE}")

    assert response.status_code == 200
    assert response.json() == {
        "used_units": 12,
        "available_units": 88,
        "next_reset_at": "2026-07-01T00:00:00Z",
    }


async def test_usage_returns_404_when_quota_is_not_configured(api_client) -> None:
    client, _ = api_client

    with patch.object(
        quota_routes.service,
        "get_feature_usage",
        AsyncMock(side_effect=ValueError("quota is not configured")),
    ):
        response = await client.get(f"/quota/orgs/{ORG_ID}/features/{FEATURE}")

    assert response.status_code == 404


async def test_consumer_reserves_and_commits(api_client) -> None:
    client, db = api_client
    reservation_id = uuid4()
    reserved = {
        "reservation_id": reservation_id,
        "units": 2,
        "status": "reserved",
    }

    with (
        patch.object(
            consumer_routes.service,
            "reserve_quota",
            AsyncMock(return_value=reserved),
        ) as reserve,
        patch.object(
            consumer_routes.service,
            "commit_reservation",
            AsyncMock(return_value={**reserved, "status": "committed"}),
        ) as commit,
    ):
        response = await client.post(
            f"/user/orgs/{ORG_ID}/features/{FEATURE}/items",
            headers={"Idempotency-Key": "request-1"},
            json={"items": ["one", "two"]},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "committed"
    reserve.assert_awaited_once()
    reserve_call = reserve.await_args
    assert reserve_call is not None
    assert reserve_call.args[3:5] == (2, "request-1")
    commit.assert_awaited_once_with(db, reservation_id)


async def test_consumer_releases_after_downstream_failure(api_client) -> None:
    client, db = api_client
    reservation_id = uuid4()
    reserved = {
        "reservation_id": reservation_id,
        "units": 1,
        "status": "reserved",
    }

    with (
        patch.object(
            consumer_routes.service,
            "reserve_quota",
            AsyncMock(return_value=reserved),
        ),
        patch.object(
            consumer_routes.service,
            "release_reservation",
            AsyncMock(return_value={**reserved, "status": "released"}),
        ) as release,
    ):
        response = await client.post(
            f"/user/orgs/{ORG_ID}/features/{FEATURE}/items",
            headers={"Idempotency-Key": "request-1"},
            json={"items": ["one"], "simulate_failure": True},
        )

    assert response.status_code == 502
    release.assert_awaited_once_with(db, reservation_id)


async def test_consumer_returns_429_when_quota_is_exhausted(api_client) -> None:
    client, _ = api_client

    with patch.object(
        consumer_routes.service,
        "reserve_quota",
        AsyncMock(
            side_effect=consumer_routes.service.QuotaExceededError(
                "not enough quota available"
            )
        ),
    ):
        response = await client.post(
            f"/user/orgs/{ORG_ID}/features/{FEATURE}/items",
            headers={"Idempotency-Key": "request-1"},
            json={"items": ["one"]},
        )

    assert response.status_code == 429


async def test_consumer_requires_items_and_idempotency_key(api_client) -> None:
    client, _ = api_client

    missing_key = await client.post(
        f"/user/orgs/{ORG_ID}/features/{FEATURE}/items",
        json={"items": ["one"]},
    )
    empty_items = await client.post(
        f"/user/orgs/{ORG_ID}/features/{FEATURE}/items",
        headers={"Idempotency-Key": "request-1"},
        json={"items": []},
    )

    assert missing_key.status_code == 422
    assert empty_items.status_code == 422
