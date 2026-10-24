import logging
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .database import SessionLocal, create_tables, engine, get_db
from .models import Notification

logging.basicConfig(level=logging.INFO)


class OrderCreatedRequest(BaseModel):
    event_type: str = Field(pattern=r"^order\.created$")
    order_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    total_amount: Decimal = Field(ge=0)


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    message: str
    created_at: datetime


@asynccontextmanager
async def lifespan(_: FastAPI):
    await create_tables()
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Notification Service", lifespan=lifespan)
Database = Annotated[AsyncSession, Depends(get_db)]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/notifications", response_model=NotificationResponse)
async def create_notification(
    event: OrderCreatedRequest,
    db: Database,
) -> Notification:
    existing = await db.scalar(
        select(Notification).where(Notification.order_id == event.order_id)
    )
    if existing is not None:
        return existing

    notification = Notification(
        order_id=event.order_id,
        message=f"Order {event.order_id} created successfully",
    )
    db.add(notification)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(Notification).where(Notification.order_id == event.order_id)
        )
        if existing is None:
            raise
        return existing
    await db.refresh(notification)
    logging.info("Saved notification for order %s", event.order_id)
    return notification


@app.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(db: Database) -> list[Notification]:
    result = await db.scalars(select(Notification).order_by(Notification.id))
    return list(result.all())
