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
from app.main import app, get_order_event_publisher
from app.messaging import RabbitMQPublishError
from app.models import Base, Order, Product


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
    event_publisher: EventPublisherStub,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with database() as session:
        session.add(
            Product(
                id=12,
                name="Widget",
                price=Decimal("19.99"),
                available_quantity=3,
            )
        )
        await session.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_product_create_list_and_get(client: httpx.AsyncClient) -> None:
    create_response = await client.post(
        "/products",
        json={"name": "  Mouse ", "price": "12.50", "available_quantity": 8},
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["name"] == "Mouse"
    assert Decimal(created["price"]) == Decimal("12.50")

    list_response = await client.get("/products")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 2

    get_response = await client.get(f"/products/{created['id']}")
    assert get_response.status_code == 200
    assert get_response.json() == created


@pytest.mark.asyncio
async def test_create_order_decrements_stock_and_publishes_event(
    client: httpx.AsyncClient,
    database: async_sessionmaker[AsyncSession],
    event_publisher: EventPublisherStub,
) -> None:
    response = await client.post("/orders", json={"product_id": 12, "quantity": 2})

    assert response.status_code == 201
    order = response.json()
    assert order["product_id"] == 12
    assert order["quantity"] == 2
    assert Decimal(order["total_amount"]) == Decimal("39.98")
    assert order["status"] == "created"
    assert order["created_at"]
    assert event_publisher.events == [
        {
            "event_type": "order.created",
            "order_id": order["id"],
            "product_id": 12,
            "quantity": 2,
            "total_amount": 39.98,
        }
    ]
    async with database() as session:
        product = await session.get(Product, 12)
    assert product is not None and product.available_quantity == 1

    list_response = await client.get("/orders")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    get_response = await client.get(f"/orders/{order['id']}")
    assert get_response.status_code == 200
    assert get_response.json() == order
    assert (await client.get("/orders/999999")).status_code == 404


@pytest.mark.asyncio
async def test_missing_product_does_not_create_order(
    client: httpx.AsyncClient,
    database: async_sessionmaker[AsyncSession],
    event_publisher: EventPublisherStub,
) -> None:
    response = await client.post("/orders", json={"product_id": 999, "quantity": 1})

    assert response.status_code == 404
    async with database() as session:
        count = await session.scalar(select(func.count()).select_from(Order))
    assert count == 0
    assert event_publisher.events == []


@pytest.mark.asyncio
async def test_insufficient_stock_does_not_create_order(
    client: httpx.AsyncClient,
    database: async_sessionmaker[AsyncSession],
    event_publisher: EventPublisherStub,
) -> None:
    response = await client.post("/orders", json={"product_id": 12, "quantity": 4})

    assert response.status_code == 409
    assert response.json()["detail"] == "Insufficient stock"
    async with database() as session:
        count = await session.scalar(select(func.count()).select_from(Order))
        product = await session.get(Product, 12)
    assert count == 0
    assert product is not None and product.available_quantity == 3
    assert event_publisher.events == []


@pytest.mark.asyncio
async def test_invalid_order_is_rejected(
    client: httpx.AsyncClient,
    event_publisher: EventPublisherStub,
) -> None:
    response = await client.post("/orders", json={"product_id": 0, "quantity": 0})

    assert response.status_code == 422
    assert event_publisher.events == []


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

    response = await client.post("/orders", json={"product_id": 12, "quantity": 1})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Order was created, but its event could not be published"
    )
    async with database() as session:
        count = await session.scalar(select(func.count()).select_from(Order))
        product = await session.get(Product, 12)
    assert count == 1
    assert product is not None and product.available_quantity == 2
