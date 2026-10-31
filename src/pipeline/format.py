from datetime import UTC, datetime
from zoneinfo import ZoneInfo

NBSP = "\u00a0"
_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€"}
_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


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


def format_compact(value: float) -> str:
    """Cifra corta para la barra: sin decimales a partir de 100."""
    return format_number(value, 0 if abs(value) >= 100 else 2)


def format_sparkline(values: list[float], width: int = 16) -> str:
    if not values:
        return ""
    if len(values) > width:
        step = (len(values) - 1) / (width - 1)
        values = [values[round(index * step)] for index in range(width)]
    low, high = min(values), max(values)
    if high == low:
        return _SPARK_BLOCKS[len(_SPARK_BLOCKS) // 2] * len(values)
    scale = (len(_SPARK_BLOCKS) - 1) / (high - low)
    return "".join(_SPARK_BLOCKS[round((value - low) * scale)] for value in values)
