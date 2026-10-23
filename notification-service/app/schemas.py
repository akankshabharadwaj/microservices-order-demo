"""Pydantic request and response schemas for the Notification Service."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OrderCreatedEvent(BaseModel):
    event_type: str = Field(pattern=r"^order\.created$")
    order_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    total_amount: Decimal = Field(ge=0)


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    order_id: int
    message: str
    status: str
    created_at: datetime
