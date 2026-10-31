import os
from pathlib import Path


def _xdg_base(variable: str, fallback: str) -> Path:
    # La especificación XDG obliga a ignorar las rutas relativas.
    value = os.environ.get(variable, "")
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / fallback


def config_dir() -> Path:
    return _xdg_base("XDG_CONFIG_HOME", ".config") / "pipeline"


def data_dir() -> Path:
    return _xdg_base("XDG_DATA_HOME", ".local/share") / "pipeline"


def config_path() -> Path:
    return config_dir() / "config.toml"


def secrets_path() -> Path:
    return config_dir() / "secrets.toml"


def database_path() -> Path:
    return data_dir() / "pipeline.db"
