import os
import socket

import pytest

_skipped = []


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Ningún test toca el directorio personal real ni las claves del entorno."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("PIPELINE_EODHD_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Cualquier intento de abrir una conexión hace fallar el test."""

    def blocked(*_args, **_kwargs):
        raise AssertionError("Los tests no pueden usar la red")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def pytest_runtest_logreport(report):
    if report.skipped:
        _skipped.append(report.nodeid)


def pytest_sessionfinish(session):
    # En CI, un test omitido es un fallo: si no, faltar Node.js dejaría sin probar plugin/Model.js.
    if os.environ.get("PIPELINE_FAIL_ON_SKIP") and _skipped:
        print(f"\nTests omitidos con PIPELINE_FAIL_ON_SKIP: {len(_skipped)}")
        session.exitstatus = 1
