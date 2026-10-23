"""RabbitMQ consumer for order-created events."""

import asyncio
import json
import logging

import aio_pika
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractRobustChannel,
    AbstractRobustConnection,
    AbstractRobustQueue,
)
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import Notification
from .schemas import OrderCreatedEvent

logger = logging.getLogger(__name__)
QUEUE_NAME = "order_notifications"


class NotificationConsumer:
    def __init__(
        self,
        url: str,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._url = url
        self._session_factory = session_factory
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractRobustChannel | None = None
        self._queue: AbstractRobustQueue | None = None
        self._consumer_tag: str | None = None

    async def start(self) -> None:
        try:
            self._connection = await aio_pika.connect_robust(self._url, timeout=5.0)
            self._channel = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=10)
            self._queue = await self._channel.declare_queue(
                QUEUE_NAME,
                durable=True,
            )
            self._consumer_tag = await self._queue.consume(self.process_message)
        except (aio_pika.exceptions.AMQPException, OSError, asyncio.TimeoutError):
            await self.close()
            raise

    async def process_message(self, message: AbstractIncomingMessage) -> None:
        try:
            event = OrderCreatedEvent.model_validate_json(message.body)
        except (ValidationError, ValueError):
            logger.exception("Rejecting invalid order.created event")
            await message.reject(requeue=False)
            return

        try:
            await self._store_notification(event)
        except Exception:
            logger.exception(
                "Failed to process order.created event for order_id=%s",
                event.order_id,
            )
            await message.nack(requeue=True)
            return

        await message.ack()

    async def _store_notification(self, event: OrderCreatedEvent) -> None:
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(Notification.id).where(Notification.order_id == event.order_id)
            )
            if existing is not None:
                return

            notification = Notification(
                event_type=event.event_type,
                order_id=event.order_id,
                message=f"Order {event.order_id} created.",
                status="unread",
            )
            session.add(notification)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(Notification.id).where(
                        Notification.order_id == event.order_id
                    )
                )
                if existing is None:
                    raise

    async def close(self) -> None:
        if self._queue is not None and self._consumer_tag is not None:
            await self._queue.cancel(self._consumer_tag)
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._queue = None
        self._consumer_tag = None
