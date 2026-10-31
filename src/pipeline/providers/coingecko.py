import math
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from pipeline.errors import ProviderError
from pipeline.providers.base import ProviderQuote

# Solo para anotaciones: los lectores importan este módulo y no deben cargar código de red.
if TYPE_CHECKING:
    from pipeline.http import HttpClient

BASE_URL = "https://api.coingecko.com/api/v3/coins/markets"
SPARKLINE_SPAN_SECONDS = 7 * 86_400

_COIN_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "XRP": "ripple", "NEAR": "near"}


def _number(value: Any) -> float | None:
    # bool es subclase de int: `true` no debe colarse como precio.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _timestamp(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return int(parsed.timestamp()) if parsed.tzinfo else None


def _series(item: dict[str, Any], price_time: int) -> tuple[tuple[int, float], ...]:
    sparkline = item.get("sparkline_in_7d")
    raw = sparkline.get("price") if isinstance(sparkline, dict) else None
    if not isinstance(raw, list) or len(raw) < 2:
        return ()
    # La API solo da una lista de precios de 7 días: el tiempo de cada punto es aproximado,
    # suficiente para dibujar la forma. Los huecos se descartan.
    step = SPARKLINE_SPAN_SECONDS / (len(raw) - 1)
    points = []
    for index, value in enumerate(raw):
        number = _number(value)
        if number is not None:
            points.append((int(price_time - (len(raw) - 1 - index) * step), number))
    return tuple(points)


class CoinGecko:
    name = "coingecko"
    display_name = "CoinGecko"
    attribution = "Powered by CoinGecko"
    asset_class = "crypto"
    price_kind = "live"
    # Sus términos piden refrescar la caché al menos cada 24 horas.
    retention_seconds = 86_400

    def request_count(self, symbols: tuple[str, ...]) -> int:
        return 1 if symbols else 0

    def fetch(
        self, symbols: tuple[str, ...], currency: str, client: HttpClient
    ) -> list[ProviderQuote]:
        symbol_by_id = {_COIN_IDS[symbol]: symbol for symbol in symbols}
        query = urlencode(
            {
                "vs_currency": currency.lower(),
                "ids": ",".join(symbol_by_id),
                "sparkline": "true",
                "price_change_percentage": "24h",
            }
        )
        payload = client.get_json(f"{BASE_URL}?{query}")
        if not isinstance(payload, list):
            raise ProviderError("CoinGecko: se esperaba una lista")

        quotes = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            symbol = symbol_by_id.get(item.get("id"))
            price = _number(item.get("current_price"))
            price_time = _timestamp(item.get("last_updated"))
            if symbol is None or price is None or price_time is None:
                continue
            quotes.append(
                ProviderQuote(
                    symbol=symbol,
                    price=price,
                    change_percent=_number(item.get("price_change_percentage_24h")),
                    price_time=price_time,
                    series=_series(item, price_time),
                )
            )
        return quotes
