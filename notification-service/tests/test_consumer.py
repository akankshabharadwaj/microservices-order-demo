from collections.abc import AsyncGenerator
from collections.abc import Awaitable, Callable

import aio_pika
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.consumer import NotificationConsumer
from app.models import Base, Notification


EVENT_BODY = (
    b'{"event_type":"order.created","order_id":1,"product_id":3,'
    b'"quantity":2,"total_amount":1300}'
)


class MessageStub:
    def __init__(self, body: bytes = EVENT_BODY) -> None:
        self.body = body
        self.acks = 0
        self.rejects: list[bool] = []
        self.nacks: list[bool] = []
        self.before_ack: Callable[[], Awaitable[None]] | None = None

    async def ack(self) -> None:
        if self.before_ack is not None:
            await self.before_ack()
        self.acks += 1

    async def reject(self, requeue: bool) -> None:
        self.rejects.append(requeue)

    async def nack(self, requeue: bool) -> None:
        self.nacks.append(requeue)


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
    yield session_factory

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_consumer_stores_then_acknowledges_event(
    database: async_sessionmaker[AsyncSession],
) -> None:
    consumer = NotificationConsumer("amqp://unused", database)
    message = MessageStub()

    async def assert_persisted_before_ack() -> None:
        async with database() as session:
            count = await session.scalar(
                select(func.count()).select_from(Notification)
            )
        assert count == 1

    message.before_ack = assert_persisted_before_ack
    await consumer.process_message(message)  # type: ignore[arg-type]

    assert message.acks == 1
    assert message.rejects == []
    assert message.nacks == []
    async with database() as session:
        notification = await session.scalar(select(Notification))
    assert notification is not None
    assert notification.event_type == "order.created"
    assert notification.order_id == 1
    assert notification.message == "Order 1 created."
    assert notification.status == "unread"


@pytest.mark.asyncio
async def test_duplicate_order_event_is_acknowledged_without_duplicate_row(
    database: async_sessionmaker[AsyncSession],
) -> None:
    consumer = NotificationConsumer("amqp://unused", database)

    await consumer.process_message(MessageStub())  # type: ignore[arg-type]
    duplicate = MessageStub()
    await consumer.process_message(duplicate)  # type: ignore[arg-type]

    assert duplicate.acks == 1
    async with database() as session:
        count = await session.scalar(
            select(func.count()).select_from(Notification)
        )
    assert count == 1


@pytest.mark.asyncio
async def test_invalid_event_is_rejected_without_acknowledgment(
    database: async_sessionmaker[AsyncSession],
) -> None:
    consumer = NotificationConsumer("amqp://unused", database)
    message = MessageStub(b'{"event_type":"order.updated","order_id":1}')

    await consumer.process_message(message)  # type: ignore[arg-type]

    assert message.acks == 0
    assert message.rejects == [False]


@pytest.mark.asyncio
async def test_database_error_nacks_for_requeue(
    database: async_sessionmaker[AsyncSession],
) -> None:
    class BrokenSessionFactory:
        def __call__(self) -> object:
            raise RuntimeError("database unavailable")

    consumer = NotificationConsumer(
        "amqp://unused",
        BrokenSessionFactory(),  # type: ignore[arg-type]
    )
    message = MessageStub()

    await consumer.process_message(message)  # type: ignore[arg-type]

    assert message.acks == 0
    assert message.nacks == [True]
