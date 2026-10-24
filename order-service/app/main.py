from contextlib import asynccontextmanager
from decimal import Decimal
import os
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import create_tables, engine, get_db
from .models import Order, Product

NOTIFICATION_SERVICE_URL = os.environ.get(
    "NOTIFICATION_SERVICE_URL", "http://notification-service:8000"
)


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(ge=0)
    stock: int = Field(ge=0)


class ProductResponse(BaseModel):
    id: int
    name: str
    price: Decimal
    stock: int


class OrderCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class OrderResponse(BaseModel):
    id: int
    product_id: int
    quantity: int
    total_amount: Decimal
    status: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    app.state.notification_client = httpx.AsyncClient(
        base_url=NOTIFICATION_SERVICE_URL.rstrip("/"),
        timeout=5.0,
    )
    try:
        yield
    finally:
        await app.state.notification_client.aclose()
        await engine.dispose()


app = FastAPI(title="Order Service", lifespan=lifespan)
Database = Annotated[AsyncSession, Depends(get_db)]


async def get_notification_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.notification_client


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(data: ProductCreate, db: Database) -> Product:
    product = Product(**data.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@app.get("/products", response_model=list[ProductResponse])
async def list_products(db: Database) -> list[Product]:
    result = await db.scalars(select(Product).order_by(Product.id))
    return list(result.all())


@app.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(
    data: OrderCreate,
    db: Database,
    notification_client: Annotated[
        httpx.AsyncClient, Depends(get_notification_client)
    ],
) -> Order:
    async with db.begin():
        product = await db.scalar(
            select(Product).where(Product.id == data.product_id).with_for_update()
        )
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
        if product.stock < data.quantity:
            raise HTTPException(status_code=409, detail="Insufficient stock")

        product.stock -= data.quantity
        order = Order(
            product_id=product.id,
            quantity=data.quantity,
            total_amount=product.price * data.quantity,
        )
        db.add(order)
    await db.refresh(order)

    try:
        response = await notification_client.post(
            "/notifications",
            json={
                "event_type": "order.created",
                "order_id": order.id,
                "product_id": order.product_id,
                "quantity": order.quantity,
                "total_amount": str(order.total_amount),
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="Order was created, but notification service failed",
        ) from exc
    return order


@app.get("/orders", response_model=list[OrderResponse])
async def list_orders(db: Database) -> list[Order]:
    result = await db.scalars(select(Order).order_by(Order.id))
    return list(result.all())
