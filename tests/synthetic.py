"""Datos y dobles inventados. Nunca respuestas grabadas de un proveedor."""

import io
import json
import urllib.error
from datetime import UTC, datetime
from email.message import Message

NOW = 1_800_000_000

COIN_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "XRP": "ripple", "NEAR": "near"}
PRICES = {"BTC": 1000.0, "ETH": 200.0, "XRP": 2.0, "NEAR": 5.0}


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z")


def coin(symbol, price=None, change=1.5, updated=NOW, sparkline=(1.0, 2.0, 3.0)):
    return {
        "id": COIN_IDS[symbol],
        "symbol": symbol.lower(),
        "current_price": PRICES[symbol] if price is None else price,
        "price_change_percentage_24h": change,
        "last_updated": iso(updated),
        "sparkline_in_7d": {"price": list(sparkline)},
    }


def markets(symbols=tuple(COIN_IDS), updated=NOW, factor=1.0):
    return [coin(symbol, price=PRICES[symbol] * factor, updated=updated) for symbol in symbols]


class FakeResponse:
    def __init__(self, body):
        self._stream = io.BytesIO(body)

    def read(self, size=-1):
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def http_error(code, headers=None):
    message = Message()
    for name, value in (headers or {}).items():
        message[name] = value
    return urllib.error.HTTPError(
        "https://example.test/", code, "synthetic", message, io.BytesIO(b"")
    )


class FakeOpener:
    """Devuelve las respuestas en orden: objetos JSON, bytes o excepciones que lanzar."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, bytes):
            return FakeResponse(response)
        return FakeResponse(json.dumps(response).encode())
