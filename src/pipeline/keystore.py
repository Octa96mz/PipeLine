import contextlib
import os
import re
import stat
import tempfile
import tomllib
from pathlib import Path

from pipeline.errors import KeystoreError

PROVIDERS = ("coingecko", "eodhd")

# Limitar el alfabeto evita tener que escapar el valor al escribir el TOML.
_KEY_FORMAT = re.compile(r"^[A-Za-z0-9._~+/=-]{8,512}$")


def _check_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise KeystoreError(f"Proveedor desconocido: {provider}")


def env_variable(provider: str) -> str:
    return f"PIPELINE_{provider.upper()}_API_KEY"


def _read_keys(path: Path) -> dict[str, str]:
    # O_NOFOLLOW y fstat sobre el mismo descriptor: se comprueba justo el fichero que se lee.
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise KeystoreError(f"{path}: no se pudo abrir: {error.strerror}") from error

    with os.fdopen(descriptor, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise KeystoreError(f"{path}: no es un fichero normal")
        if info.st_uid != os.getuid():
            raise KeystoreError(f"{path}: pertenece a otro usuario")
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o077:
            raise KeystoreError(f"{path}: permisos inseguros ({mode:03o}); usá chmod 600")
        try:
            raw = tomllib.load(file)
        except tomllib.TOMLDecodeError:
            # El mensaje del parser podría citar parte del contenido: no se propaga.
            raise KeystoreError(f"{path}: TOML no válido") from None

    keys = raw.get("keys", {})
    if not isinstance(keys, dict) or not all(isinstance(value, str) for value in keys.values()):
        raise KeystoreError(f"{path}: formato no válido")
    return keys


def has_key(provider: str, path: Path) -> bool:
    _check_provider(provider)
    return provider in _read_keys(path)


def load_key(provider: str, path: Path) -> str | None:
    """Devuelve la clave del proveedor. La variable de entorno tiene prioridad sobre el fichero."""
    _check_provider(provider)
    from_env = os.environ.get(env_variable(provider))
    if from_env:
        return from_env
    return _read_keys(path).get(provider)


def save_key(provider: str, key: str, path: Path) -> None:
    """Guarda la clave con permisos 600 mediante reemplazo atómico."""
    _check_provider(provider)
    if not _KEY_FORMAT.fullmatch(key):
        raise KeystoreError("La clave tiene un formato no válido")

    keys = _read_keys(path)
    keys[provider] = key
    body = "[keys]\n" + "".join(f'{name} = "{keys[name]}"\n' for name in sorted(keys))

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # mkstemp crea el temporal con permisos 600 antes de escribir nada en él.
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".secrets-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(body)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise
