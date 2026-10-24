import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import json
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal, engine, get_db
from app.main import app, get_notification_client
from app.models import Base, Order


class NotificationClientStub:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.error: httpx.HTTPError | None = None

    async def post(
        self,
        url: str,
        json: dict[str, object],
    ) -> httpx.Response:
        request = httpx.Request(
            "POST",
            f"http://notification-service{url}",
            json=json,
        )
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return httpx.Response(200, json={"id": 1}, request=request)


@pytest_asyncio.fixture
async def notification_client() -> AsyncGenerator[NotificationClientStub, None]:
    stub = NotificationClientStub()

    async def override_notification_client() -> NotificationClientStub:
        return stub

    app.dependency_overrides[get_notification_client] = override_notification_client
    yield stub


@pytest_asyncio.fixture
async def client(
    notification_client: NotificationClientStub,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    del notification_client
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
async def test_order_flow_updates_stock_and_calls_notification_service(
    client: httpx.AsyncClient,
    notification_client: NotificationClientStub,
) -> None:
    product_response = await client.post(
        "/products",
        json={"name": "ESP32", "price": 650, "stock": 20},
    )
    assert product_response.status_code == 201
    product = product_response.json()

    order_response = await client.post(
        "/orders",
        json={"product_id": product["id"], "quantity": 2},
    )
    assert order_response.status_code == 201
    assert order_response.json()["total_amount"] == "1300.00"
    assert (await client.get("/products")).json()[0]["stock"] == 18
    assert (await client.get("/orders")).json() == [order_response.json()]

    request = notification_client.requests[0]
    assert request.url.path == "/notifications"
    assert json.loads(request.content) == {
        "event_type": "order.created",
        "order_id": order_response.json()["id"],
        "product_id": product["id"],
        "quantity": 2,
        "total_amount": "1300.00",
    }


@pytest.mark.asyncio
async def test_missing_product_and_insufficient_stock_are_rejected(
    client: httpx.AsyncClient,
    notification_client: NotificationClientStub,
) -> None:
    assert (await client.get("/health")).json() == {"status": "healthy"}
    assert (
        await client.post(
            "/orders",
            json={"product_id": 999, "quantity": 1},
        )
    ).status_code == 404

    product = await client.post(
        "/products",
        json={"name": "ESP32", "price": 650, "stock": 2},
    )
    response = await client.post(
        "/orders",
        json={"product_id": product.json()["id"], "quantity": 3},
    )
    assert response.status_code == 409
    assert notification_client.requests == []


@pytest.mark.asyncio
async def test_notification_failure_is_reported_after_order_is_committed(
    client: httpx.AsyncClient,
    notification_client: NotificationClientStub,
) -> None:
    notification_client.error = httpx.ConnectError(
        "connection failed",
        request=httpx.Request(
            "POST",
            "http://notification-service/notifications",
        ),
    )
    product = await client.post(
        "/products",
        json={"name": "ESP32", "price": 650, "stock": 2},
    )

    response = await client.post(
        "/orders",
        json={"product_id": product.json()["id"], "quantity": 1},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Order was created, but notification service failed"
    )
    async with SessionLocal() as db:
        orders = await db.scalars(select(Order))
        assert len(list(orders.all())) == 1
