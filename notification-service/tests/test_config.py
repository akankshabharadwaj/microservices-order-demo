import pytest

from app.config import get_database_url


@pytest.mark.parametrize(
    ("configured_url", "expected_url"),
    [
        (
            "postgresql+psycopg://user:pass@notification-db:5432/notification_db",
            "postgresql+asyncpg://user:pass@notification-db:5432/notification_db",
        ),
        (
            "postgresql://user:pass@notification-db:5432/notification_db",
            "postgresql+asyncpg://user:pass@notification-db:5432/notification_db",
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
