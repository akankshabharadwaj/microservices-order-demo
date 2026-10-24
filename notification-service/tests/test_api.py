import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal, engine, get_db
from app.main import app
from app.models import Base, Notification


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_rest_notification_creation_is_idempotent(
    client: httpx.AsyncClient,
) -> None:
    event = {
        "event_type": "order.created",
        "order_id": 12,
        "product_id": 3,
        "quantity": 2,
        "total_amount": "1300.00",
    }

    first_response = await client.post("/notifications", json=event)
    duplicate_response = await client.post("/notifications", json=event)

    assert first_response.status_code == 200
    assert first_response.json()["message"] == "Order 12 created successfully"
    assert duplicate_response.json() == first_response.json()
    async with SessionLocal() as db:
        count = await db.scalar(
            select(func.count()).select_from(Notification)
        )
    assert count == 1


@pytest.mark.asyncio
async def test_health_and_notification_listing(client: httpx.AsyncClient) -> None:
    async with SessionLocal() as db:
        db.add(
            Notification(
                order_id=1,
                message="Order 1 created successfully",
            )
        )
        await db.commit()

    assert (await client.get("/health")).json() == {"status": "healthy"}
    response = await client.get("/notifications")
    assert response.status_code == 200
    assert response.json()[0]["order_id"] == 1
    assert response.json()[0]["message"] == "Order 1 created successfully"


@pytest.mark.asyncio
async def test_only_order_created_events_are_accepted(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/notifications",
        json={
            "event_type": "order.updated",
            "order_id": 12,
            "product_id": 3,
            "quantity": 2,
            "total_amount": "1300.00",
        },
    )

    assert response.status_code == 422
