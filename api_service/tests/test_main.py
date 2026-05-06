import importlib
import sys
from contextlib import contextmanager

import pytest


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class FakeConnection:
    """Stand-in for a SQLAlchemy connection used by API endpoints.

    Each call to ``execute`` consumes the next planned response. A response is either
    a list of rows (returned as a ``FakeResult``) or an exception instance (re-raised).
    """

    def __init__(self, responses):
        self._responses = list(responses)

    def execute(self, *args, **kwargs):
        if not self._responses:
            raise AssertionError("No more fake responses queued")
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return FakeResult(response)


class FakeEngine:
    def __init__(self, responses):
        self._responses = responses

    @contextmanager
    def connect(self):
        yield FakeConnection(self._responses)


REQUIRED_ENV = {
    "DB_USER": "user",
    "DB_PASSWORD": "password",
    "DB_NAME": "db",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
}


def reload_main(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    sys.modules.pop("api_service.main", None)
    return importlib.import_module("api_service.main")


@pytest.fixture
def main_module(monkeypatch):
    return reload_main(monkeypatch)


def test_startup_fails_without_env(monkeypatch):
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sys.modules.pop("api_service.main", None)

    with pytest.raises(RuntimeError, match="Missing required environment variable"):
        importlib.import_module("api_service.main")


def test_get_current_risk_returns_404_when_no_snapshot(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "engine", FakeEngine([[]]))
    with pytest.raises(main_module.HTTPException) as excinfo:
        main_module.get_current_risk()

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "No predictions found"


def test_get_current_risk_returns_500_on_error(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "engine", FakeEngine([RuntimeError("db down")]))
    with pytest.raises(main_module.HTTPException) as excinfo:
        main_module.get_current_risk()

    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Failed to fetch current risk predictions"


def test_get_predictions_handles_no_snapshot(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "engine", FakeEngine([[]]))
    with pytest.raises(main_module.HTTPException) as excinfo:
        main_module.get_predictions()

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "No predictions found"


def test_get_history_handles_execution_error(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "engine", FakeEngine([RuntimeError("query failed")]))
    with pytest.raises(main_module.HTTPException) as excinfo:
        main_module.get_history(geo_code="DEU")

    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Failed to fetch history"


def test_require_api_key_no_op_when_unset(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "API_KEY", None)
    # Must not raise regardless of the header value.
    main_module.require_api_key(x_api_key=None)
    main_module.require_api_key(x_api_key="anything")


def test_require_api_key_rejects_invalid(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "API_KEY", "secret-token")
    with pytest.raises(main_module.HTTPException) as excinfo:
        main_module.require_api_key(x_api_key="wrong")
    assert excinfo.value.status_code == 401


def test_require_api_key_accepts_match(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "API_KEY", "secret-token")
    main_module.require_api_key(x_api_key="secret-token")


def test_get_history_by_citizen_returns_404_when_no_rows(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "engine", FakeEngine([[]]))
    with pytest.raises(main_module.HTTPException) as excinfo:
        main_module.get_history_by_citizen(geo_code="FR", top=5, since=None)

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "No per-nationality history found"


def test_get_history_by_citizen_returns_500_on_db_error(main_module, monkeypatch):
    monkeypatch.setattr(
        main_module, "engine", FakeEngine([RuntimeError("query exploded")])
    )
    with pytest.raises(main_module.HTTPException) as excinfo:
        main_module.get_history_by_citizen(geo_code="FR", top=5, since=None)

    assert excinfo.value.status_code == 500
