"""Application configuration for the Order Service."""

import os


def get_database_url() -> str:
    """Return the configured database URL or fail with a useful message."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    for scheme in (
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
        "postgresql://",
        "postgres://",
    ):
        if database_url.startswith(scheme):
            return database_url.replace(scheme, "postgresql+asyncpg://", 1)
    if database_url.startswith("postgresql+"):
        raise RuntimeError(
            "DATABASE_URL must use the asyncpg driver, such as "
            "postgresql+asyncpg://user:password@host:5432/database"
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
