import argparse
import getpass
import json
import sqlite3
import sys
import time
import warnings
from collections.abc import Sequence
from typing import Any

from pipeline import __version__, keystore, paths
from pipeline.config import Config, load_config
from pipeline.db import Database
from pipeline.errors import FetchInProgress, PipelineError
from pipeline.format import format_clock, format_sparkline
from pipeline.providers import CRYPTO_PROVIDER
from pipeline.redact import redact_text, setup_logging
from pipeline.report import build_report, error_report
from pipeline.schedule import active_cooldown

DAY_SECONDS = 86_400


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
            until = active_cooldown(database, provider.name, now)
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
    # Import diferido: los comandos de lectura no deben cargar el código de red.
    from pipeline.collector import fetch_lock, make_client, run_fetch

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
        cooling = active_cooldown(database, provider.name, now) is not None
        if not args.scheduled and not args.yes and not cooling:
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


def _load_report(config: Config, now: int) -> dict[str, Any]:
    if not paths.database_path().exists():
        return build_report(config, None, now)
    with Database.open_readonly(paths.database_path()) as database:
        return build_report(config, database, now)


def _quote_line(row: dict[str, Any]) -> str:
    if row["price"] is None:
        return f"  {row['symbol']:<6} {row['state_label']}"
    change = row["change_text"] or ""
    line = f"  {row['symbol']:<6} {row['price_text']:>14} {change:>10}  {row['age_text']}"
    if row["state"] == "held":
        return f"{line}  retenido\n         {row['reason']}"
    return f"{line}  {row['state_label']}" if row["state"] == "stale" else line


def _status() -> int:
    config = load_config(paths.config_path())
    report = _load_report(config, _now())
    provider = report["providers"][0]

    print(f"{provider['name']} · {provider['attribution']}")
    print(
        f"  Llamadas hechas (24 h): {provider['calls_24h']} "
        "(el proveedor no publica un límite sin clave)"
    )
    attempt = provider["last_attempt"]
    if attempt is None:
        print("  Último intento: ninguno")
    else:
        print(f"  Último intento: {attempt['age_text']}, {attempt['outcome_label']}")
        if attempt["detail"] and attempt["outcome"] != "ok":
            print(f"  Detalle: {attempt['detail']}")
    if provider["cooldown_until_text"]:
        print(f"  En pausa por 429 hasta las {provider['cooldown_until_text']}")
    if provider["offline_streak"] >= 2:
        print(
            f"  Sin conexión en {provider['offline_streak']} pasadas seguidas; "
            f"próximo intento automático hacia las {provider['next_attempt_text']}"
        )
    crypto = report["groups"][0]
    print(f"{crypto['title']} ({report['currency']})")
    for row in crypto["items"]:
        print(_quote_line(row))
    print("Índices y acciones: sin proveedor configurado")
    return 0


def _show() -> int:
    config = load_config(paths.config_path())
    report = _load_report(config, _now())
    for group in report["groups"]:
        print(group["title"])
        for row in group["items"]:
            if row["price"] is None:
                print(f"  {row['symbol']:<6} {row['name']:<18} {row['state_label']}")
                continue
            line = (
                f"  {row['symbol']:<6} {row['name']:<18} {format_sparkline(row['series']):<16} "
                f"{row['price_text']:>14} {row['change_text'] or '':>10}  {row['state_label']}"
            )
            print(f"{line}\n         {row['reason']}" if row["state"] == "held" else line)
    for provider in report["providers"]:
        print(provider["attribution"])
    return 0


def _json(pretty: bool) -> int:
    """Siempre imprime un JSON válido: la barra lo necesita aunque algo vaya mal."""
    now = _now()
    code = 0
    try:
        report = _load_report(load_config(paths.config_path()), now)
    except (PipelineError, sqlite3.Error, OSError) as error:
        report = error_report(redact_text(str(error)), now)
        code = 1
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            allow_nan=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
        )
    )
    return code


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
    commands.add_parser("show", help="muestra los precios y minigráficos en el terminal")
    json_parser = commands.add_parser("json", help="imprime los datos para la barra y el panel")
    json_parser.add_argument("--pretty", action="store_true", help="con sangría, para leerlo")
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
            case "show":
                return _show()
            case "json":
                return _json(args.pretty)
    except FetchInProgress as error:
        # Coincidir con un fetch manual no es un fallo: la siguiente pasada del timer ya actuará.
        if args.scheduled:
            print(f"pipeline: {error}")
            return 0
        print(f"pipeline: {error}", file=sys.stderr)
        return 1
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
