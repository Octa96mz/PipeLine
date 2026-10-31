import argparse
import getpass
import sys
import warnings
from collections.abc import Sequence

from pipeline import __version__, keystore, paths
from pipeline.errors import PipelineError
from pipeline.redact import setup_logging


def _read_hidden(prompt: str) -> str:
    if not sys.stdin.isatty():
        raise PipelineError(
            "set-key necesita un terminal para ocultar la clave; "
            "sin terminal, usá la variable de entorno"
        )
    # getpass solo avisa cuando no puede ocultar lo escrito; aquí eso debe ser un error.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning:
            raise PipelineError("No se puede ocultar lo que se escribe en este terminal") from None


def _set_key(provider: str) -> int:
    path = paths.secrets_path()
    if keystore.has_key(provider, path):
        answer = input(f"Ya hay una clave de {provider}. ¿Sustituirla? [s/N] ")
        if answer.strip().lower() not in ("s", "si", "sí"):
            print("Sin cambios.")
            return 0
    key = _read_hidden(f"Clave de {provider} (no se mostrará): ").strip()
    if not key:
        raise PipelineError("No se ha introducido ninguna clave")
    keystore.save_key(provider, key, path)
    print(f"Clave de {provider} guardada con permisos 600.")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline", description=__doc__)
    parser.add_argument("--version", action="version", version=f"pipeline {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    set_key = commands.add_parser("set-key", help="guarda la clave de un proveedor")
    set_key.add_argument("provider", choices=keystore.PROVIDERS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    setup_logging()
    args = _parser().parse_args(argv)
    try:
        return _set_key(args.provider)
    except PipelineError as error:
        print(f"pipeline: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt, EOFError:
        print("\nCancelado.", file=sys.stderr)
        return 130
