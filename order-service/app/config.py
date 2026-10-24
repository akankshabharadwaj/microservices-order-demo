"""Application configuration for the Order Service."""

import os

from sqlalchemy.engine import make_url


def get_database_url() -> str:
    """Return the configured database URL or fail with a useful message."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() in {"postgres", "postgresql"}:
        return parsed_url.set(drivername="postgresql+asyncpg").render_as_string(
            hide_password=False
        )
    return database_url


def get_inventory_service_url() -> str:
    """Return the base URL for the Inventory Service."""
    service_url = os.getenv("INVENTORY_SERVICE_URL")
    if not service_url:
        raise RuntimeError("INVENTORY_SERVICE_URL environment variable is required")
    return service_url.rstrip("/")


def get_rabbitmq_url() -> str:
    """Return the configured RabbitMQ connection URL."""
    rabbitmq_url = os.getenv("RABBITMQ_URL")
    if not rabbitmq_url:
        raise RuntimeError("RABBITMQ_URL environment variable is required")
    return rabbitmq_url
