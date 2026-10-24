import pytest
from sqlalchemy.engine import make_url

from app import database
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
        (
            "postgresql+psycopg2://user:pass@inventory-db:5432/inventory_db",
            "postgresql+asyncpg://user:pass@inventory-db:5432/inventory_db",
        ),
        (
            "postgresql+custom_driver://user:pass@inventory-db:5432/inventory_db",
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

    database_url = get_database_url()
    assert database_url == expected_url
    assert make_url(database_url).drivername == "postgresql+asyncpg"


@pytest.mark.asyncio
async def test_database_initialization_retries_after_connection_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConnectionStub:
        async def run_sync(self, callback: object) -> None:
            return None

    class EngineStub:
        attempts = 0

        def begin(self) -> "EngineStub":
            return self

        async def __aenter__(self) -> ConnectionStub:
            self.attempts += 1
            if self.attempts == 1:
                raise TimeoutError
            return ConnectionStub()

        async def __aexit__(self, *_: object) -> None:
            return None

    engine = EngineStub()

    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(database, "get_engine", lambda: engine)
    monkeypatch.setattr(database.asyncio, "sleep", no_wait)

    await database.init_db()

    assert engine.attempts == 2
