import math

from pipeline.db import Quote
from pipeline.providers.base import ProviderQuote

MAX_CLOCK_SKEW_SECONDS = 300
# Un dato anterior más viejo que esto no sirve de referencia. Así, un salto real rechazado
# no bloquea el símbolo para siempre.
MAX_REFERENCE_AGE_SECONDS = 86_400


def _is_positive(value: float) -> bool:
    return math.isfinite(value) and value > 0


def rejection_reason(
    new: ProviderQuote,
    previous: Quote | None,
    currency: str | None,
    max_jump_percent: int,
    now: int,
) -> str | None:
    """Devuelve por qué se descarta el dato, o None si es aceptable."""
    if not _is_positive(new.price):
        return "precio no válido"
    if new.change_percent is not None and not math.isfinite(new.change_percent):
        return "variación no válida"
    if new.price_time > now + MAX_CLOCK_SKEW_SECONDS:
        return "fecha futura"
    if not all(_is_positive(value) for _, value in new.series):
        return "serie no válida"
    if (
        previous is not None
        and previous.currency == currency
        and now - previous.fetched_at <= MAX_REFERENCE_AGE_SECONDS
    ):
        jump = abs(new.price - previous.price) / previous.price * 100
        if jump > max_jump_percent:
            return f"salto del {jump:.0f} %"
    return None
