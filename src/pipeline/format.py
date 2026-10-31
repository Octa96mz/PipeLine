from datetime import UTC, datetime
from zoneinfo import ZoneInfo

NBSP = "\u00a0"
_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€"}


def format_number(value: float, decimals: int) -> str:
    """Formato es_ES: coma decimal y punto de millares a partir de cinco cifras enteras."""
    sign = "-" if value < 0 else ""
    whole, _, fraction = f"{abs(value):.{decimals}f}".partition(".")
    if len(whole) >= 5:
        whole = f"{int(whole):,}".replace(",", ".")
    return f"{sign}{whole},{fraction}" if fraction else f"{sign}{whole}"


def _price_decimals(value: float) -> int:
    magnitude = abs(value)
    if magnitude >= 1:
        return 2
    return 4 if magnitude >= 0.01 else 6


def format_price(value: float, currency: str | None) -> str:
    text = format_number(value, _price_decimals(value))
    # Sin moneda (índices), el valor se expresa en puntos.
    return f"{text}{NBSP}{_CURRENCY_SYMBOLS[currency]}" if currency else text


def format_percent(value: float) -> str:
    return f"{'+' if value >= 0 else ''}{format_number(value, 2)}{NBSP}%"


def format_age(seconds: int) -> str:
    if seconds < 60:
        return "ahora"
    if seconds < 3600:
        return f"hace {seconds // 60} min"
    if seconds < 86_400:
        return f"hace {seconds // 3600} h"
    return f"hace {seconds // 86_400} d"


def format_clock(timestamp: int, timezone: str) -> str:
    return datetime.fromtimestamp(timestamp, UTC).astimezone(ZoneInfo(timezone)).strftime("%H:%M")
