from collections.abc import AsyncGenerator
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app, get_inventory_client, get_order_event_publisher
from app.messaging import RabbitMQPublishError
from app.models import Base, Order


class InventoryStub:
    def __init__(self) -> None:
        self.status_code = 200
        self.payload: object = {"price": "19.99"}
        self.error: httpx.HTTPError | None = None
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return httpx.Response(self.status_code, json=self.payload)


class EventPublisherStub:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.fail = False

    async def publish_order_created(self, order: Order) -> None:
        if self.fail:
            raise RabbitMQPublishError("broker unavailable")
        self.events.append(
            {
                "event_type": "order.created",
                "order_id": order.id,
                "product_id": order.product_id,
                "quantity": order.quantity,
                "total_amount": float(order.total_amount),
            }
        )


@pytest_asyncio.fixture
async def database() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield session_factory
    app.dependency_overrides.clear()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def inventory_stub() -> AsyncGenerator[InventoryStub, None]:
    stub = InventoryStub()

    async def override_inventory_client() -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(stub),
            base_url="http://inventory.test",
        ) as inventory_client:
            yield inventory_client

    app.dependency_overrides[get_inventory_client] = override_inventory_client
    yield stub
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def event_publisher() -> AsyncGenerator[EventPublisherStub, None]:
    stub = EventPublisherStub()

    def override_publisher() -> EventPublisherStub:
        return stub

    app.dependency_overrides[get_order_event_publisher] = override_publisher
    yield stub
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(
    database: async_sessionmaker[AsyncSession],
    inventory_stub: InventoryStub,
    event_publisher: EventPublisherStub,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    del database, inventory_stub, event_publisher
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_create_order_reserves_inventory_and_calculates_total(
    client: httpx.AsyncClient,
    inventory_stub: InventoryStub,
    event_publisher: EventPublisherStub,
) -> None:
    response = await client.post("/orders", json={"product_id": 12, "quantity": 3})

    assert response.status_code == 201
    order = response.json()
    assert order["product_id"] == 12
    assert order["quantity"] == 3
    assert Decimal(order["total_amount"]) == Decimal("59.97")
    assert order["status"] == "created"
    assert order["created_at"]
    assert len(inventory_stub.requests) == 1
    assert str(inventory_stub.requests[0].url) == (
        "http://inventory.test/products/12/reserve"
    )
    assert inventory_stub.requests[0].method == "POST"
    assert inventory_stub.requests[0].content == b'{"quantity":3}'
    assert event_publisher.events == [
        {
            "event_type": "order.created",
            "order_id": order["id"],
            "product_id": 12,
            "quantity": 3,
            "total_amount": 59.97,
        }
    ]

    list_response = await client.get("/orders")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = await client.get(f"/orders/{order['id']}")
    assert get_response.status_code == 200
    assert get_response.json() == order

    missing_response = await client.get("/orders/999999")
    assert missing_response.status_code == 404


@pytest.mark.asyncio
async def test_inventory_rejection_does_not_create_order(
    client: httpx.AsyncClient,
    inventory_stub: InventoryStub,
    event_publisher: EventPublisherStub,
    database: async_sessionmaker[AsyncSession],
) -> None:
    inventory_stub.status_code = 409
    inventory_stub.payload = {"detail": "Insufficient stock"}

    response = await client.post("/orders", json={"product_id": 12, "quantity": 3})

    assert response.status_code == 409
    assert response.json()["detail"] == "Insufficient stock"
    assert event_publisher.events == []
    async with database() as session:
        count = await session.scalar(select(func.count()).select_from(Order))
    assert count == 0


@pytest.mark.asyncio
async def test_inventory_unavailable_returns_service_unavailable(
    client: httpx.AsyncClient,
    inventory_stub: InventoryStub,
) -> None:
    inventory_stub.error = httpx.ConnectError(
        "connection failed",
        request=httpx.Request("POST", "http://inventory.test/products/12/reserve"),
    )

    response = await client.post("/orders", json={"product_id": 12, "quantity": 3})

    assert response.status_code == 503
    assert response.json()["detail"] == "Inventory Service is unavailable"


@pytest.mark.asyncio
async def test_invalid_order_is_rejected_before_inventory_call(
    client: httpx.AsyncClient,
    inventory_stub: InventoryStub,
) -> None:
    response = await client.post("/orders", json={"product_id": 0, "quantity": 0})

    assert response.status_code == 422
    assert inventory_stub.requests == []


@pytest.mark.asyncio
async def test_health_check(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_broker_failure_is_reported_after_order_is_saved(
    client: httpx.AsyncClient,
    event_publisher: EventPublisherStub,
    database: async_sessionmaker[AsyncSession],
) -> None:
    event_publisher.fail = True

    response = await client.post("/orders", json={"product_id": 12, "quantity": 3})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Order was created, but its event could not be published"
    )
    async with database() as session:
        count = await session.scalar(select(func.count()).select_from(Order))
    assert count == 1
