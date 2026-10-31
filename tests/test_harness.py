import socket
from pathlib import Path

import pytest

from pipeline import paths


def test_network_is_blocked():
    with pytest.raises(AssertionError, match="red"):
        socket.create_connection(("192.0.2.1", 443), timeout=0.01)


def test_paths_stay_inside_the_test_directory(tmp_path):
    for path in (paths.config_path(), paths.secrets_path(), paths.database_path()):
        assert path.is_relative_to(tmp_path)


def test_relative_xdg_paths_are_ignored(monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "relative/path")
    assert paths.data_dir() == Path.home() / ".local/share/pipeline"
