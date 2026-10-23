from collections.abc import AsyncGenerator
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app import main
from app.database import get_db
from app.main import app
from app.models import Base, Product


@pytest_asyncio.fixture
async def database() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine: AsyncEngine = create_async_engine(
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
async def client(
    database: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with database() as session:
        await session.execute(delete(Product))
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_product_lifecycle_and_reservation(client: httpx.AsyncClient) -> None:
    health_response = await client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}

    create_response = await client.post(
        "/products",
        json={"name": "Keyboard", "price": "49.99", "available_quantity": 5},
    )
    assert create_response.status_code == 201
    product = create_response.json()
    assert product["name"] == "Keyboard"
    assert Decimal(product["price"]) == Decimal("49.99")
    assert product["available_quantity"] == 5

    product_id = product["id"]
    list_response = await client.get("/products")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = await client.get(f"/products/{product_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == product_id

    reserve_response = await client.post(
        f"/products/{product_id}/reserve", json={"quantity": 2}
    )
    assert reserve_response.status_code == 200
    assert reserve_response.json()["available_quantity"] == 3

    updated_response = await client.get(f"/products/{product_id}")
    assert updated_response.json()["available_quantity"] == 3


@pytest.mark.asyncio
async def test_reservation_errors(client: httpx.AsyncClient) -> None:
    create_response = await client.post(
        "/products",
        json={"name": "Mouse", "price": 10, "available_quantity": 1},
    )
    product_id = create_response.json()["id"]

    insufficient_response = await client.post(
        f"/products/{product_id}/reserve", json={"quantity": 2}
    )
    assert insufficient_response.status_code == 409

    missing_response = await client.get("/products/999999")
    assert missing_response.status_code == 404

    missing_reservation_response = await client.post(
        "/products/999999/reserve", json={"quantity": 1}
    )
    assert missing_reservation_response.status_code == 404


@pytest.mark.asyncio
async def test_request_validation(client: httpx.AsyncClient) -> None:
    invalid_product_response = await client.post(
        "/products",
        json={"name": "   ", "price": -1, "available_quantity": -1},
    )
    assert invalid_product_response.status_code == 422

    invalid_reservation_response = await client.post(
        "/products/1/reserve", json={"quantity": 0}
    )
    assert invalid_reservation_response.status_code == 422
