from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, Notification


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
async def client(
    database: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_notification_listing_and_detail(
    client: httpx.AsyncClient,
    database: async_sessionmaker[AsyncSession],
) -> None:
    async with database() as session:
        notification = Notification(
            event_type="order.created",
            order_id=22,
            message="Order 22 created.",
            status="unread",
        )
        session.add(notification)
        await session.commit()
        await session.refresh(notification)
        notification_id = notification.id

    health_response = await client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}

    list_response = await client.get("/notifications")
    assert list_response.status_code == 200
    assert list_response.json() == [
        {
            "id": notification_id,
            "event_type": "order.created",
            "order_id": 22,
            "message": "Order 22 created.",
            "status": "unread",
            "created_at": list_response.json()[0]["created_at"],
        }
    ]
    assert list_response.json()[0]["created_at"]

    detail_response = await client.get(f"/notifications/{notification_id}")
    assert detail_response.status_code == 200
    assert detail_response.json() == list_response.json()[0]

    missing_response = await client.get("/notifications/99999")
    assert missing_response.status_code == 404
