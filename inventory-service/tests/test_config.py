import pytest

from app.config import get_database_url


@pytest.mark.parametrize(
    ("configured_url", "expected_url"),
    [
        (
            "postgresql+psycopg://user:pass@inventory-db:5432/inventory_db",
            "postgresql+asyncpg://user:pass@inventory-db:5432/inventory_db",
        ),
        (
            "postgresql://user:pass@inventory-db:5432/inventory_db",
            "postgresql+asyncpg://user:pass@inventory-db:5432/inventory_db",
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
