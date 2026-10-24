import pytest
from sqlalchemy.engine import make_url

from app.config import get_database_url


@pytest.mark.parametrize(
    ("configured_url", "expected_url"),
    [
        (
            "postgresql+psycopg://user:pass@order-db:5432/order_db",
            "postgresql+asyncpg://user:pass@order-db:5432/order_db",
        ),
        (
            "postgresql://user:pass@order-db:5432/order_db",
            "postgresql+asyncpg://user:pass@order-db:5432/order_db",
        ),
        (
            "postgresql+psycopg2://user:pass@order-db:5432/order_db",
            "postgresql+asyncpg://user:pass@order-db:5432/order_db",
        ),
        (
            "postgresql+custom_driver://user:pass@order-db:5432/order_db",
            "postgresql+asyncpg://user:pass@order-db:5432/order_db",
        ),
    ],
)
def test_database_url_uses_asyncpg_driver(
    monkeypatch: pytest.MonkeyPatch,
    configured_url: str,
    expected_url: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", configured_url)

    database_url = get_database_url()
    assert database_url == expected_url
    assert make_url(database_url).drivername == "postgresql+asyncpg"
