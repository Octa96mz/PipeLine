import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pipeline.errors import ConfigError

KNOWN_CRYPTO = ("BTC", "ETH", "XRP", "NEAR")
KNOWN_INDICES = ("SPX", "DJI", "IXIC", "IBEX")
CURRENCIES = ("USD", "EUR")

MAX_BAR_ITEMS = 3
# El plan gratuito de EODHD admite 20 llamadas al día.
MAX_EODHD_BUDGET = 20

_STOCK_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")


@dataclass(frozen=True)
class Display:
    currency: str = "USD"
    timezone: str = "Europe/Madrid"
    bar_items: tuple[str, ...] = ("BTC", "SPX")


@dataclass(frozen=True)
class Assets:
    crypto: tuple[str, ...] = KNOWN_CRYPTO
    indices: tuple[str, ...] = KNOWN_INDICES
    stocks: tuple[str, ...] = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA")

    def all_symbols(self) -> tuple[str, ...]:
        return self.crypto + self.indices + self.stocks


@dataclass(frozen=True)
class Collector:
    crypto_interval_minutes: int = 5
    request_timeout_seconds: int = 10
    max_retries: int = 3
    eodhd_daily_call_budget: int = 18


@dataclass(frozen=True)
class Validation:
    max_jump_percent: int = 50
    stale_after_minutes: int = 30


@dataclass(frozen=True)
class Config:
    display: Display = field(default_factory=Display)
    assets: Assets = field(default_factory=Assets)
    collector: Collector = field(default_factory=Collector)
    validation: Validation = field(default_factory=Validation)


def _table(raw: dict[str, Any], name: str, allowed: set[str]) -> dict[str, Any]:
    table = raw.get(name, {})
    if not isinstance(table, dict):
        raise ConfigError(f"[{name}] debe ser una tabla")
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"[{name}] tiene claves desconocidas: {', '.join(unknown)}")
    return table


def _int(table: dict[str, Any], section: str, key: str, default: int, low: int, high: int) -> int:
    value = table.get(key, default)
    # bool es subclase de int: sin esta comprobación, `true` valdría como 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{section}.{key} debe ser un entero")
    if not low <= value <= high:
        raise ConfigError(f"{section}.{key} debe estar entre {low} y {high}")
    return value


def _symbols(
    table: dict[str, Any], section: str, key: str, default: tuple[str, ...]
) -> tuple[str, ...]:
    value = table.get(key, default)
    if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{section}.{key} debe ser una lista de símbolos")
    if len(set(value)) != len(value):
        raise ConfigError(f"{section}.{key} tiene símbolos repetidos")
    return tuple(value)


def _subset(symbols: tuple[str, ...], known: tuple[str, ...], key: str) -> tuple[str, ...]:
    unknown = sorted(set(symbols) - set(known))
    if unknown:
        raise ConfigError(f"assets.{key} tiene símbolos no admitidos: {', '.join(unknown)}")
    return symbols


def _parse_assets(raw: dict[str, Any]) -> Assets:
    table = _table(raw, "assets", {"crypto", "indices", "stocks"})
    defaults = Assets()
    stocks = _symbols(table, "assets", "stocks", defaults.stocks)
    for symbol in stocks:
        if not _STOCK_SYMBOL.fullmatch(symbol):
            raise ConfigError(f"assets.stocks tiene un símbolo no válido: {symbol}")
    assets = Assets(
        crypto=_subset(
            _symbols(table, "assets", "crypto", defaults.crypto), KNOWN_CRYPTO, "crypto"
        ),
        indices=_subset(
            _symbols(table, "assets", "indices", defaults.indices), KNOWN_INDICES, "indices"
        ),
        stocks=stocks,
    )
    if len(set(assets.all_symbols())) != len(assets.all_symbols()):
        raise ConfigError("[assets] repite un símbolo entre categorías")
    return assets


def _parse_display(raw: dict[str, Any], assets: Assets) -> Display:
    table = _table(raw, "display", {"currency", "timezone", "bar_items"})
    defaults = Display()

    currency = table.get("currency", defaults.currency)
    if currency not in CURRENCIES:
        raise ConfigError(f"display.currency debe ser uno de: {', '.join(CURRENCIES)}")

    timezone = table.get("timezone", defaults.timezone)
    try:
        ZoneInfo(timezone)
    # ZoneInfoNotFoundError deriva de KeyError.
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise ConfigError(f"display.timezone no es válida: {timezone}") from error

    bar_items = _symbols(table, "display", "bar_items", defaults.bar_items)
    if not 1 <= len(bar_items) <= MAX_BAR_ITEMS:
        raise ConfigError(f"display.bar_items debe tener entre 1 y {MAX_BAR_ITEMS} símbolos")
    missing = sorted(set(bar_items) - set(assets.all_symbols()))
    if missing:
        raise ConfigError(f"display.bar_items no está en [assets]: {', '.join(missing)}")

    return Display(currency=currency, timezone=timezone, bar_items=bar_items)


def _parse_collector(raw: dict[str, Any]) -> Collector:
    section = "collector"
    defaults = Collector()
    table = _table(raw, section, set(Collector.__dataclass_fields__))
    return Collector(
        crypto_interval_minutes=_int(
            table, section, "crypto_interval_minutes", defaults.crypto_interval_minutes, 2, 1440
        ),
        request_timeout_seconds=_int(
            table, section, "request_timeout_seconds", defaults.request_timeout_seconds, 1, 60
        ),
        max_retries=_int(table, section, "max_retries", defaults.max_retries, 0, 5),
        eodhd_daily_call_budget=_int(
            table,
            section,
            "eodhd_daily_call_budget",
            defaults.eodhd_daily_call_budget,
            0,
            MAX_EODHD_BUDGET,
        ),
    )


def _parse_validation(raw: dict[str, Any]) -> Validation:
    section = "validation"
    defaults = Validation()
    table = _table(raw, section, set(Validation.__dataclass_fields__))
    return Validation(
        max_jump_percent=_int(
            table, section, "max_jump_percent", defaults.max_jump_percent, 1, 1000
        ),
        stale_after_minutes=_int(
            table, section, "stale_after_minutes", defaults.stale_after_minutes, 1, 1440
        ),
    )


def parse_config(raw: dict[str, Any]) -> Config:
    unknown = sorted(set(raw) - {"display", "assets", "collector", "validation"})
    if unknown:
        raise ConfigError(f"Secciones desconocidas: {', '.join(unknown)}")
    assets = _parse_assets(raw)
    return Config(
        display=_parse_display(raw, assets),
        assets=assets,
        collector=_parse_collector(raw),
        validation=_parse_validation(raw),
    )


def load_config(path: Path) -> Config:
    """Carga la configuración. Si el fichero no existe, se usan los valores por defecto."""
    try:
        with path.open("rb") as file:
            raw = tomllib.load(file)
    except FileNotFoundError:
        return Config()
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: TOML no válido: {error}") from error
    except OSError as error:
        raise ConfigError(f"{path}: no se pudo leer: {error.strerror}") from error
    return parse_config(raw)
