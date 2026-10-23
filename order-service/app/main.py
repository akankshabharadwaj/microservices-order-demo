"""Order Service application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from decimal import Decimal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_inventory_service_url, get_rabbitmq_url
from .database import close_db, get_db, init_db
from .messaging import OrderEventPublisher, RabbitMQPublishError
from .models import Order
from .schemas import InventoryProduct, OrderCreate, OrderResponse


@asynccontextmanager
async def lifespan(application: FastAPI):
    publisher = OrderEventPublisher(get_rabbitmq_url())
    try:
        await init_db()
        application.state.order_event_publisher = publisher
        yield
    finally:
        try:
            await publisher.close()
        finally:
            await close_db()


app = FastAPI(title="Order Service", lifespan=lifespan)


def get_order_event_publisher(request: Request) -> OrderEventPublisher:
    return request.app.state.order_event_publisher


async def get_inventory_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        base_url=get_inventory_service_url(),
        timeout=5.0,
    ) as client:
        yield client


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_data: OrderCreate,
    db: AsyncSession = Depends(get_db),
    inventory_client: httpx.AsyncClient = Depends(get_inventory_client),
    event_publisher: OrderEventPublisher = Depends(get_order_event_publisher),
) -> Order:
    try:
        response = await inventory_client.post(
            f"/products/{order_data.product_id}/reserve",
            json={"quantity": order_data.quantity},
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inventory Service is unavailable",
        ) from exc

    if response.is_error:
        if response.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT):
            try:
                error_body = response.json()
            except ValueError:
                error_body = None
            detail = (
                error_body["detail"]
                if isinstance(error_body, dict) and isinstance(error_body.get("detail"), str)
                else "Inventory reservation failed"
            )
            raise HTTPException(status_code=response.status_code, detail=detail)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Inventory Service returned an error",
        )

    try:
        product = InventoryProduct.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Inventory Service returned an invalid response",
        ) from exc

    order = Order(
        product_id=order_data.product_id,
        quantity=order_data.quantity,
        total_amount=product.price * Decimal(order_data.quantity),
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    try:
        await event_publisher.publish_order_created(order)
    except RabbitMQPublishError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Order was created, but its event could not be published",
        ) from exc
    return order


@app.get("/orders", response_model=list[OrderResponse])
async def list_orders(db: AsyncSession = Depends(get_db)) -> list[Order]:
    result = await db.execute(select(Order).order_by(Order.id))
    return list(result.scalars().all())


@app.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: int, db: AsyncSession = Depends(get_db)) -> Order:
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order
