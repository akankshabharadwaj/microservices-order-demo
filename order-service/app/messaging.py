"""RabbitMQ publisher for order events."""

import asyncio
import json

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from .models import Order

QUEUE_NAME = "order_notifications"


class RabbitMQPublishError(Exception):
    """Raised when an order event cannot be published."""


class OrderEventPublisher:
    def __init__(self, url: str) -> None:
        self._url = url
        self._connection: AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractRobustChannel | None = None
        self._queue: aio_pika.abc.AbstractRobustQueue | None = None
        self._connection_lock = asyncio.Lock()

    async def _ensure_connected(self) -> None:
        try:
            async with self._connection_lock:
                if self._connection is None or self._connection.is_closed:
                    self._connection = await aio_pika.connect_robust(
                        self._url,
                        timeout=5.0,
                    )
                    self._channel = None
                    self._queue = None
                if self._channel is None or self._channel.is_closed:
                    self._channel = await self._connection.channel(
                        publisher_confirms=True
                    )
                    self._queue = None
                if self._queue is None:
                    self._queue = await self._channel.declare_queue(
                        QUEUE_NAME,
                        durable=True,
                    )

            if self._connection is not None:
                await self._connection.ready()
        except (aio_pika.exceptions.AMQPException, OSError, asyncio.TimeoutError) as exc:
            raise RabbitMQPublishError("Could not connect to RabbitMQ") from exc

    async def publish_order_created(self, order: Order) -> None:
        try:
            await asyncio.wait_for(self._ensure_connected(), timeout=5.0)
            if self._channel is None or self._queue is None:
                raise RabbitMQPublishError("RabbitMQ publisher is not connected")

            payload = {
                "event_type": "order.created",
                "order_id": order.id,
                "product_id": order.product_id,
                "quantity": order.quantity,
                "total_amount": float(order.total_amount),
            }
            await asyncio.wait_for(
                self._channel.default_exchange.publish(
                    aio_pika.Message(
                        body=json.dumps(payload).encode("utf-8"),
                        content_type="application/json",
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    ),
                    routing_key=self._queue.name,
                    mandatory=True,
                ),
                timeout=5.0,
            )
        except (
            aio_pika.exceptions.AMQPException,
            OSError,
            asyncio.TimeoutError,
        ) as exc:
            raise RabbitMQPublishError("Failed to publish order.created event") from exc

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._queue = None
