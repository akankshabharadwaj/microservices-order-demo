"""Order Service application entry point."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_rabbitmq_url
from .database import close_db, get_db, init_db
from .messaging import OrderEventPublisher, RabbitMQPublishError
from .models import Order, Product
from .schemas import OrderCreate, OrderResponse, ProductCreate, ProductResponse


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


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    product_data: ProductCreate,
    db: AsyncSession = Depends(get_db),
) -> Product:
    product = Product(**product_data.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@app.get("/products", response_model=list[ProductResponse])
async def list_products(db: AsyncSession = Depends(get_db)) -> list[Product]:
    result = await db.execute(select(Product).order_by(Product.id))
    return list(result.scalars().all())


@app.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_data: OrderCreate,
    db: AsyncSession = Depends(get_db),
    event_publisher: OrderEventPublisher = Depends(get_order_event_publisher),
) -> Order:
    async with db.begin():
        result = await db.execute(
            select(Product)
            .where(Product.id == order_data.product_id)
            .with_for_update()
        )
        product = result.scalar_one_or_none()
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found",
            )
        if product.available_quantity < order_data.quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Insufficient stock",
            )
        product.available_quantity -= order_data.quantity
        order = Order(
            product_id=product.id,
            quantity=order_data.quantity,
            total_amount=product.price * order_data.quantity,
        )
        db.add(order)
    await db.refresh(order)
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
