from typing import Any

from pipeline.catalog import names
from pipeline.config import Config
from pipeline.db import Database, FetchAttempt
from pipeline.format import (
    format_age,
    format_clock,
    format_compact,
    format_percent,
    format_price,
)
from pipeline.freshness import EXPIRED, STALE, freshness
from pipeline.providers import CRYPTO_PROVIDER
from pipeline.providers.base import Provider
from pipeline.schedule import active_cooldown, next_attempt_at

# Subir esta versión si cambia un campo existente. Añadir campos no la cambia.
SCHEMA_VERSION = 1
MAX_SERIES_POINTS = 48
DAY_SECONDS = 86_400

_OUTCOME_LABELS = {
    "ok": "correcto",
    "partial": "parcial",
    "rate_limited": "limitado por el proveedor (429)",
    "offline": "sin conexión",
    "error": "error",
}
_STALE_REASONS = {
    "partial": "No se pudo actualizar",
    "rate_limited": "El proveedor pide esperar",
    "offline": "Sin conexión",
    "error": "Error del proveedor",
}
_STATE_LABELS = {
    "stale": "obsoleto",
    "held": "retenido",
    "no_data": "sin datos",
    "unavailable": "no disponible",
}


def _downsample(values: list[float]) -> list[float]:
    if len(values) <= MAX_SERIES_POINTS:
        return values
    step = (len(values) - 1) / (MAX_SERIES_POINTS - 1)
    return [values[round(index * step)] for index in range(MAX_SERIES_POINTS)]


def _empty_row(symbol: str, asset_class: str, state: str, reason: str) -> dict[str, Any]:
    name, short_name = names(symbol)
    return {
        "symbol": symbol,
        "name": name,
        "short_name": short_name,
        "asset_class": asset_class,
        "state": state,
        "state_label": _STATE_LABELS[state],
        "stale": False,
        "reason": reason,
        "provider": None,
        "price": None,
        "price_text": None,
        "compact_text": None,
        "currency": None,
        "change_percent": None,
        "change_text": None,
        "direction": None,
        "kind": None,
        "price_time": None,
        "fetched_at": None,
        "age_seconds": None,
        "age_text": None,
        "series": [],
        "hold": None,
    }


def _direction(change: float | None) -> str | None:
    if change is None:
        return None
    if change > 0:
        return "up"
    return "down" if change < 0 else "flat"


def _stale_reason(attempt: FetchAttempt | None, fetched_at: int) -> str:
    if attempt is not None and attempt.outcome != "ok" and attempt.finished_at > fetched_at:
        return _STALE_REASONS[attempt.outcome]
    return "Dato antiguo"


def _row(
    symbol: str,
    provider: Provider,
    database: Database | None,
    attempt: FetchAttempt | None,
    config: Config,
    now: int,
) -> dict[str, Any]:
    asset_class = provider.asset_class
    quote = database.quote(symbol) if database else None
    if quote is None:
        return _empty_row(symbol, asset_class, "no_data", "Todavía no hay datos")

    stale_after = config.validation.stale_after_minutes * 60
    current = freshness(quote, now, stale_after, provider.retention_seconds, attempt)
    if current == EXPIRED:
        return _empty_row(symbol, asset_class, "no_data", "Más de 24 h sin refresco")

    age = max(0, now - quote.price_time)
    held = database.held_quote(symbol)
    row = _empty_row(symbol, asset_class, "no_data", "")
    row.update(
        provider=quote.provider,
        price=quote.price,
        price_text=format_price(quote.price, quote.currency),
        compact_text=format_compact(quote.price),
        currency=quote.currency,
        change_percent=quote.change_percent,
        change_text=None if quote.change_percent is None else format_percent(quote.change_percent),
        direction=_direction(quote.change_percent),
        kind=quote.kind,
        price_time=quote.price_time,
        fetched_at=quote.fetched_at,
        age_seconds=age,
        age_text=format_age(age),
        series=_downsample([value for _, value in database.series(symbol)]),
    )
    if held is not None:
        rejected_text = format_price(held.rejected_price, quote.currency)
        reason = (
            f"Retenido: salto del {held.jump_percent:.0f} % ({rejected_text}); "
            "se mantiene el último precio válido"
        )
        row.update(
            state="held",
            state_label=_STATE_LABELS["held"],
            stale=True,
            reason=reason,
            hold={
                "rejected_price": held.rejected_price,
                "rejected_price_text": rejected_text,
                "jump_percent": held.jump_percent,
                "since": held.since,
                "last_seen": held.last_seen,
                "since_text": format_age(max(0, now - held.since)),
            },
        )
    elif current == STALE:
        row.update(
            state="stale",
            state_label=_STATE_LABELS["stale"],
            stale=True,
            reason=_stale_reason(attempt, quote.fetched_at),
        )
    else:
        row.update(state="fresh", state_label=row["age_text"], reason=None)
    return row


def _provider_info(
    provider: Provider, database: Database | None, config: Config, now: int
) -> dict[str, Any]:
    timezone = config.display.timezone
    attempt = database.last_attempt(provider.name) if database else None
    until = active_cooldown(database, provider.name, now) if database else None
    streak = database.offline_streak(provider.name) if database else 0
    next_attempt = None
    if database and streak:
        next_attempt = next_attempt_at(
            database,
            provider.name,
            config.collector.crypto_interval_minutes * 60,
            config.collector.max_offline_interval_minutes * 60,
        )
    return {
        "id": provider.name,
        "name": provider.display_name,
        "attribution": provider.attribution,
        "calls_24h": database.calls_since(provider.name, now - DAY_SECONDS) if database else 0,
        # Null cuando el proveedor no publica un límite: no se inventa ninguno.
        "calls_limit": None,
        "calls_remaining": None,
        "last_attempt": None
        if attempt is None
        else {
            "finished_at": attempt.finished_at,
            "outcome": attempt.outcome,
            "outcome_label": _OUTCOME_LABELS[attempt.outcome],
            "age_text": format_age(max(0, now - attempt.finished_at)),
            "detail": attempt.detail,
        },
        "cooldown_until": until,
        "cooldown_until_text": None if until is None else format_clock(until, timezone),
        "offline_streak": streak,
        "next_attempt_at": next_attempt,
        "next_attempt_text": None if next_attempt is None else format_clock(next_attempt, timezone),
    }


def _overall_status(rows: list[dict[str, Any]]) -> str:
    available = [row for row in rows if row["state"] != "unavailable"]
    if not any(row["price"] is not None for row in available):
        return "no_data"
    return "fresh" if all(row["state"] == "fresh" for row in available) else "stale"


def _bar(
    config: Config,
    rows: dict[str, dict[str, Any]],
    status: str,
    providers: list[dict[str, Any]],
    now: int,
) -> dict[str, Any]:
    items = []
    for symbol in config.display.bar_items:
        row = rows[symbol]
        items.append(
            {
                "symbol": symbol,
                "label": row["short_name"],
                "value_text": row["compact_text"] or "—",
                "change_text": row["change_text"],
                "direction": row["direction"],
                "state": row["state"],
            }
        )

    fetched = [row["fetched_at"] for row in rows.values() if row["fetched_at"] is not None]
    updated_at = max(fetched, default=None)
    if updated_at is None:
        lines = ["Sin datos todavía"]
    else:
        clock = format_clock(updated_at, config.display.timezone)
        lines = [f"Última actualización: {clock} ({format_age(max(0, now - updated_at))})"]
    if status == "stale":
        reasons = {row["reason"] for row in rows.values() if row["stale"]}
        lines.append("Datos obsoletos: " + "; ".join(sorted(reasons)))
    lines.extend(provider["attribution"] for provider in providers)
    return {"items": items, "updated_at": updated_at, "tooltip": "\n".join(lines)}


def build_report(config: Config, database: Database | None, now: int) -> dict[str, Any]:
    """Modelo común de `json`, `status` y `show`. Solo lee: nunca usa la red."""
    provider = CRYPTO_PROVIDER
    attempt = database.last_attempt(provider.name) if database else None
    crypto = [_row(s, provider, database, attempt, config, now) for s in config.assets.crypto]

    pending = "Sin proveedor configurado"
    indices = [_empty_row(s, "index", "unavailable", pending) for s in config.assets.indices]
    stocks = [_empty_row(s, "stock", "unavailable", pending) for s in config.assets.stocks]

    every_row = [*crypto, *indices, *stocks]
    rows = {row["symbol"]: row for row in every_row}
    status = _overall_status(every_row)
    providers = [_provider_info(provider, database, config, now)]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "status": status,
        "error": None,
        "currency": config.display.currency,
        "timezone": config.display.timezone,
        "bar": _bar(config, rows, status, providers, now),
        "groups": [
            {"id": "crypto", "title": "Cripto", "items": crypto},
            {"id": "indices", "title": "Índices", "items": indices},
            {"id": "stocks", "title": "Acciones", "items": stocks},
        ],
        "providers": providers,
    }


def error_report(message: str, now: int) -> dict[str, Any]:
    """Misma estructura que un informe normal, para que la barra siempre pueda interpretarla."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "status": "error",
        "error": message,
        "currency": None,
        "timezone": None,
        "bar": {"items": [], "updated_at": None, "tooltip": f"PipeLine: {message}"},
        "groups": [],
        "providers": [],
    }
