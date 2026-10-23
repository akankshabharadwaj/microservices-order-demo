import pytest

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
    ],
)
def test_database_url_uses_asyncpg_driver(
    monkeypatch: pytest.MonkeyPatch,
    configured_url: str,
    expected_url: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", configured_url)

    assert get_database_url() == expected_url
