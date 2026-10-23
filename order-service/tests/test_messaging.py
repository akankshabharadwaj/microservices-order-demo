import json
from decimal import Decimal

import aio_pika
import pytest

from app import messaging
from app.messaging import OrderEventPublisher
from app.models import Order


class ExchangeStub:
    def __init__(self) -> None:
        self.messages: list[tuple[aio_pika.Message, str, bool]] = []

    async def publish(
        self,
        message: aio_pika.Message,
        routing_key: str,
        mandatory: bool,
    ) -> None:
        self.messages.append((message, routing_key, mandatory))


class QueueStub:
    name = "order_notifications"


class ChannelStub:
    def __init__(self) -> None:
        self.default_exchange = ExchangeStub()
        self.is_closed = False
        self.declarations: list[tuple[str, bool]] = []

    async def declare_queue(self, name: str, durable: bool) -> QueueStub:
        self.declarations.append((name, durable))
        return QueueStub()


class ConnectionStub:
    def __init__(self) -> None:
        self.is_closed = False
        self.ready_calls = 0
        self.channels: list[ChannelStub] = []

    async def channel(self, publisher_confirms: bool) -> ChannelStub:
        assert publisher_confirms
        channel = ChannelStub()
        self.channels.append(channel)
        return channel

    async def ready(self) -> None:
        self.ready_calls += 1

    async def close(self) -> None:
        self.is_closed = True


@pytest.mark.asyncio
async def test_publisher_sends_persistent_event_to_durable_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections: list[ConnectionStub] = []

    async def connect_robust(url: str, timeout: float) -> ConnectionStub:
        assert url == "amqp://broker"
        assert timeout == 5.0
        connection = ConnectionStub()
        connections.append(connection)
        return connection

    monkeypatch.setattr(messaging.aio_pika, "connect_robust", connect_robust)
    publisher = OrderEventPublisher("amqp://broker")
    order = Order(
        id=1,
        product_id=7,
        quantity=2,
        total_amount=Decimal("1300.00"),
        status="created",
    )

    await publisher.publish_order_created(order)

    channel = connections[0].channels[0]
    assert channel.declarations == [("order_notifications", True)]
    message, routing_key, mandatory = channel.default_exchange.messages[0]
    assert routing_key == "order_notifications"
    assert mandatory is True
    assert message.content_type == "application/json"
    assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    assert json.loads(message.body) == {
        "event_type": "order.created",
        "order_id": 1,
        "product_id": 7,
        "quantity": 2,
        "total_amount": 1300.0,
    }

    await publisher.close()


@pytest.mark.asyncio
async def test_publisher_reconnects_after_connection_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections: list[ConnectionStub] = []

    async def connect_robust(url: str, timeout: float) -> ConnectionStub:
        connection = ConnectionStub()
        connections.append(connection)
        return connection

    monkeypatch.setattr(messaging.aio_pika, "connect_robust", connect_robust)
    publisher = OrderEventPublisher("amqp://broker")
    order = Order(
        id=2,
        product_id=7,
        quantity=1,
        total_amount=Decimal("650.00"),
        status="created",
    )

    await publisher.publish_order_created(order)
    connections[0].is_closed = True
    await publisher.publish_order_created(order)

    assert len(connections) == 2
    assert connections[1].channels[0].default_exchange.messages
    await publisher.close()
