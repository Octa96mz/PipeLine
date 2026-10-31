import socket

import pytest


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
