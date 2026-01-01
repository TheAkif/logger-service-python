import json
from typing import Any, Dict, List, Optional

import aio_pika
from aio_pika import Message, DeliveryMode

from .settings import RABBITMQ_URL, LOG_QUEUE, LOG_DLQ

_connection: aio_pika.RobustConnection | None = None
_channel: aio_pika.RobustChannel | None = None
_queue: aio_pika.RobustQueue | None = None
_dlq: aio_pika.RobustQueue | None = None


async def connect() -> None:
    global _connection, _channel, _queue, _dlq

    _connection = await aio_pika.connect_robust(RABBITMQ_URL)
    _channel = await _connection.channel(publisher_confirms=False)

    # DLQ first
    _dlq = await _channel.declare_queue(LOG_DLQ, durable=True)

    # Main queue with dead-letter routing to DLQ
    args = {
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": LOG_DLQ,
    }
    _queue = await _channel.declare_queue(LOG_QUEUE, durable=True, arguments=args)


async def disconnect() -> None:
    global _connection, _channel, _queue, _dlq
    if _channel:
        await _channel.close()
    if _connection:
        await _connection.close()
    _connection = None
    _channel = None
    _queue = None
    _dlq = None


def _ensure_channel() -> aio_pika.RobustChannel:
    if _channel is None:
        raise RuntimeError("RabbitMQ channel not initialized")
    return _channel


async def publish_event(event: Dict[str, Any]) -> None:
    ch = _ensure_channel()
    body = json.dumps({"kind": "single", "event": event}, ensure_ascii=False).encode("utf-8")
    msg = Message(body=body, delivery_mode=DeliveryMode.PERSISTENT)
    await ch.default_exchange.publish(msg, routing_key=LOG_QUEUE)


async def publish_batch(events: List[Dict[str, Any]]) -> None:
    ch = _ensure_channel()
    body = json.dumps({"kind": "batch", "events": events}, ensure_ascii=False).encode("utf-8")
    msg = Message(body=body, delivery_mode=DeliveryMode.PERSISTENT)
    await ch.default_exchange.publish(msg, routing_key=LOG_QUEUE)
