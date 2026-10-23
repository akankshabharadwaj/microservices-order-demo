"""Application configuration for the Notification Service."""

import os


def get_database_url() -> str:
    """Return the configured database URL or fail with a useful message."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


def get_rabbitmq_url() -> str:
    """Return the configured RabbitMQ connection URL."""
    rabbitmq_url = os.getenv("RABBITMQ_URL")
    if not rabbitmq_url:
        raise RuntimeError("RABBITMQ_URL environment variable is required")
    return rabbitmq_url
