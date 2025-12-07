import importlib
import sys

import pytest


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.closed = False

    def execute(self, *args, **kwargs):
        if self._exc:
            raise self._exc
        return self._result

    def close(self):
        self.closed = True


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
    sys.modules.pop("api_service.main", None)
    return importlib.import_module("api_service.main")


@pytest.fixture
def main_module(monkeypatch):
    return reload_main(monkeypatch)


def test_startup_fails_without_env(monkeypatch):
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)
    sys.modules.pop("api_service.main", None)

    with pytest.raises(RuntimeError, match="Missing required environment variable"):
        importlib.import_module("api_service.main")


def test_get_current_risk_returns_404_when_no_data(main_module):
    fake_session = FakeSession(result=FakeResult([]))
    with pytest.raises(main_module.HTTPException) as excinfo:
        main_module.get_current_risk(session=fake_session)

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "No predictions found"


def test_get_current_risk_returns_500_on_error(main_module):
    fake_session = FakeSession(exc=RuntimeError("db down"))
    with pytest.raises(main_module.HTTPException) as excinfo:
        main_module.get_current_risk(session=fake_session)

    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Failed to fetch current risk predictions"


def test_get_predictions_handles_no_rows(main_module):
    fake_session = FakeSession(result=FakeResult([]))
    with pytest.raises(main_module.HTTPException) as excinfo:
        main_module.get_predictions(session=fake_session)

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "No predictions found"


def test_get_history_handles_execution_error(main_module):
    fake_session = FakeSession(exc=RuntimeError("query failed"))
    with pytest.raises(main_module.HTTPException) as excinfo:
        main_module.get_history(geo_code="DEU", session=fake_session)

    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Failed to fetch history"
