"""Notification Service HTTP API and RabbitMQ consumer lifecycle."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_rabbitmq_url
from .consumer import NotificationConsumer
from .database import close_db, get_db, get_session_factory, init_db
from .models import Notification
from .schemas import NotificationResponse


@asynccontextmanager
async def lifespan(application: FastAPI):
    await init_db()
    consumer = NotificationConsumer(get_rabbitmq_url(), get_session_factory())
    try:
        await consumer.start()
        application.state.notification_consumer = consumer
        yield
    finally:
        try:
            await consumer.close()
        finally:
            await close_db()


app = FastAPI(title="Notification Service", lifespan=lifespan)


@app.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    db: AsyncSession = Depends(get_db),
) -> list[Notification]:
    result = await db.execute(
        select(Notification).order_by(Notification.id)
    )
    return list(result.scalars().all())


@app.get("/notifications/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
) -> Notification:
    notification = await db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    return notification


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
