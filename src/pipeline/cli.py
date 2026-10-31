import argparse
import getpass
import sqlite3
import sys
import time
import warnings
from collections.abc import Sequence

from pipeline import __version__, keystore, paths
from pipeline.collector import active_cooldown, fetch_lock, make_client, run_fetch
from pipeline.config import load_config
from pipeline.db import Database
from pipeline.errors import PipelineError
from pipeline.format import format_age, format_clock, format_percent, format_price
from pipeline.freshness import EXPIRED, STALE, freshness
from pipeline.providers import CRYPTO_PROVIDER
from pipeline.redact import setup_logging

DAY_SECONDS = 86_400
_OUTCOME_LABELS = {
    "ok": "correcto",
    "partial": "parcial",
    "rate_limited": "limitado por el proveedor (429)",
    "offline": "sin conexión",
    "error": "error",
}


def _now() -> int:
    return int(time.time())


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


def _plan_text(symbols: tuple[str, ...], max_retries: int, calls_today: int) -> str:
    provider = CRYPTO_PROVIDER
    count = provider.request_count(symbols)
    return (
        f"{provider.display_name}: {count} llamada(s), hasta {count * (max_retries + 1)} "
        f"con reintentos. Hechas en las últimas 24 h: {calls_today}."
    )


def _dry_run(symbols: tuple[str, ...], max_retries: int, timezone: str) -> int:
    provider = CRYPTO_PROVIDER
    now = _now()
    calls = 0
    until = None
    if paths.database_path().exists():
        with Database.open_readonly(paths.database_path()) as database:
            calls = database.calls_since(provider.name, now - DAY_SECONDS)
            until = active_cooldown(database, provider, now)
    print(_plan_text(symbols, max_retries, calls))
    if until is not None:
        print(f"Ahora no se llamaría: en pausa por 429 hasta las {format_clock(until, timezone)}.")
    print("Simulación: no se ha hecho ninguna llamada.")
    return 0


def _confirm(prompt: str) -> None:
    """Un fetch manual gasta llamadas: exige confirmarlo o pasar --yes."""
    if not sys.stdin.isatty():
        raise PipelineError("Un fetch manual sin terminal necesita --yes")
    answer = input(f"{prompt} ¿Continuar? [s/N] ")
    if answer.strip().lower() not in ("s", "si", "sí"):
        raise _Declined


class _Declined(Exception):
    pass


def _fetch(args: argparse.Namespace) -> int:
    config = load_config(paths.config_path())
    provider = CRYPTO_PROVIDER
    symbols = config.assets.crypto
    timezone = config.display.timezone
    if not symbols:
        print("No hay símbolos de cripto configurados.")
        return 0
    if args.dry_run:
        return _dry_run(symbols, config.collector.max_retries, timezone)

    now = _now()
    with (
        fetch_lock(paths.data_dir() / "fetch.lock"),
        Database.open(paths.database_path()) as database,
    ):
        if not args.scheduled and not args.yes and active_cooldown(database, provider, now) is None:
            calls = database.calls_since(provider.name, now - DAY_SECONDS)
            try:
                _confirm(_plan_text(symbols, config.collector.max_retries, calls))
            except _Declined:
                print("Sin cambios: no se ha hecho ninguna llamada.")
                return 0
        client = make_client(database, provider, config, now)
        result = run_fetch(database, provider, symbols, config, client, now, args.scheduled)

    match result.status:
        case "ok":
            print(f"{provider.display_name}: actualizados {', '.join(result.saved)}.")
        case "partial":
            print(f"{provider.display_name}: actualizados {', '.join(result.saved)}.")
            print(f"Descartados: {result.detail}.")
        case "rate_limited" | "cooldown":
            clock = format_clock(result.cooldown_until, timezone)
            print(f"{provider.display_name}: en pausa por 429 hasta las {clock}; datos obsoletos.")
        case "offline":
            print(f"{provider.display_name}: sin conexión; datos obsoletos.")
        case "error":
            print(f"{provider.display_name}: {result.detail}; datos obsoletos.", file=sys.stderr)
            return 1
    return 0


def _quote_line(symbol, database, attempt, config, now) -> str:
    quote = database.quote(symbol) if database else None
    state = None
    if quote is not None:
        state = freshness(
            quote,
            now,
            config.validation.stale_after_minutes * 60,
            CRYPTO_PROVIDER.retention_seconds,
            attempt,
        )
    if quote is None or state == EXPIRED:
        return f"  {symbol:<6} sin datos"
    change = "" if quote.change_percent is None else format_percent(quote.change_percent)
    age = format_age(now - quote.price_time)
    marker = "  obsoleto" if state == STALE else ""
    return (
        f"  {symbol:<6} {format_price(quote.price, quote.currency):>14} {change:>10}  {age}{marker}"
    )


def _status() -> int:
    config = load_config(paths.config_path())
    provider = CRYPTO_PROVIDER
    timezone = config.display.timezone
    now = _now()
    database = None
    if paths.database_path().exists():
        database = Database.open_readonly(paths.database_path())
    try:
        calls = database.calls_since(provider.name, now - DAY_SECONDS) if database else 0
        attempt = database.last_attempt(provider.name) if database else None
        until = active_cooldown(database, provider, now) if database else None

        print(f"{provider.display_name} · {provider.attribution}")
        print(f"  Llamadas hechas (24 h): {calls} (el proveedor no publica un límite sin clave)")
        if attempt is None:
            print("  Último intento: ninguno")
        else:
            age = format_age(now - attempt.finished_at)
            print(f"  Último intento: {age}, {_OUTCOME_LABELS[attempt.outcome]}")
            if attempt.detail and attempt.outcome != "ok":
                print(f"  Detalle: {attempt.detail}")
        if until is not None:
            print(f"  En pausa por 429 hasta las {format_clock(until, timezone)}")
        print(f"Cripto ({config.display.currency})")
        for symbol in config.assets.crypto:
            print(_quote_line(symbol, database, attempt, config, now))
    finally:
        if database:
            database.close()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline", description="Precios de mercado de solo lectura para la barra de Omarchy."
    )
    parser.add_argument("--version", action="version", version=f"pipeline {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    set_key = commands.add_parser("set-key", help="guarda la clave de un proveedor")
    set_key.add_argument("provider", choices=keystore.PROVIDERS)

    fetch = commands.add_parser("fetch", help="consulta a los proveedores y guarda los datos")
    fetch.add_argument("--yes", action="store_true", help="no pide confirmación")
    fetch.add_argument("--dry-run", action="store_true", help="muestra el plan sin hacer llamadas")
    fetch.add_argument(
        "--scheduled", action="store_true", help="modo del timer: solo llama si toca, sin preguntar"
    )

    commands.add_parser("status", help="muestra el estado del colector y los datos guardados")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    setup_logging()
    args = _parser().parse_args(argv)
    try:
        match args.command:
            case "set-key":
                return _set_key(args.provider)
            case "fetch":
                return _fetch(args)
            case "status":
                return _status()
    except PipelineError as error:
        print(f"pipeline: {error}", file=sys.stderr)
        return 1
    except sqlite3.Error as error:
        print(f"pipeline: error de base de datos: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt, EOFError:
        print("\nCancelado.", file=sys.stderr)
        return 130
    raise AssertionError(f"Comando sin implementar: {args.command}")
