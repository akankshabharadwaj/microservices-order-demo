"""Pydantic request and response schemas for the Order Service."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OrderCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    quantity: int
    total_amount: Decimal
    status: str
    created_at: datetime


class InventoryProduct(BaseModel):
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
