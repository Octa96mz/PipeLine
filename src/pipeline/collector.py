import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from pipeline.config import Config
from pipeline.db import Database, Quote
from pipeline.errors import FetchInProgress, NetworkError, ProviderError, RateLimited
from pipeline.http import HttpClient
from pipeline.providers.base import Provider
from pipeline.schedule import active_cooldown, next_attempt_at
from pipeline.validate import rejection_reason

LOG_RETENTION_SECONDS = 30 * 86_400
# El timer no dispara exactamente cada N minutos: sin este margen, una pasada se saltaría.
DUE_TOLERANCE_SECONDS = 30


@dataclass(frozen=True)
class FetchResult:
    # ok, partial, rate_limited, offline, error, cooldown o not_due.
    status: str
    saved: tuple[str, ...] = ()
    detail: str | None = None
    cooldown_until: int | None = None


@contextmanager
def fetch_lock(path: Path) -> Iterator[None]:
    """Impide dos fetch simultáneos, que duplicarían las llamadas al proveedor."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FetchInProgress("Ya hay otro fetch en curso") from None
        yield
    finally:
        os.close(descriptor)


def make_client(database: Database, provider: Provider, config: Config, now: int) -> HttpClient:
    return HttpClient(
        on_request=lambda: database.record_api_call(provider.name, now),
        timeout=config.collector.request_timeout_seconds,
        max_retries=config.collector.max_retries,
    )


def run_fetch(
    database: Database,
    provider: Provider,
    symbols: tuple[str, ...],
    config: Config,
    client: HttpClient,
    now: int,
    scheduled: bool,
) -> FetchResult:
    """Pasada de un proveedor. Si algo falla, los datos anteriores se quedan como estaban."""
    database.delete_quotes_older_than(provider.name, now - provider.retention_seconds)
    database.prune_logs(now - LOG_RETENTION_SECONDS)

    # El cooldown se respeta siempre, también en un fetch manual.
    until = active_cooldown(database, provider.name, now)
    if until is not None:
        return FetchResult("cooldown", cooldown_until=until)
    if scheduled:
        due = next_attempt_at(
            database,
            provider.name,
            config.collector.crypto_interval_minutes * 60,
            config.collector.max_offline_interval_minutes * 60,
        )
        if due is not None and now < due - DUE_TOLERANCE_SECONDS:
            return FetchResult("not_due")

    currency = config.display.currency
    try:
        fetched = provider.fetch(symbols, currency, client)
    except RateLimited as error:
        until = now + error.retry_after
        database.set_cooldown(provider.name, until)
        database.record_attempt(provider.name, now, "rate_limited", str(error))
        return FetchResult("rate_limited", detail=str(error), cooldown_until=until)
    except NetworkError as error:
        database.record_attempt(provider.name, now, "offline", str(error))
        return FetchResult("offline", detail=str(error))
    except ProviderError as error:
        database.record_attempt(provider.name, now, "error", str(error))
        return FetchResult("error", detail=str(error))

    saved = []
    problems = []
    by_symbol = {quote.symbol: quote for quote in fetched}
    for symbol in symbols:
        item = by_symbol.get(symbol)
        if item is None:
            problems.append(f"{symbol}: sin dato en la respuesta")
            continue
        rejection = rejection_reason(
            item,
            database.quote(symbol),
            currency,
            config.validation.max_jump_percent,
            now,
        )
        if rejection is not None:
            problems.append(f"{symbol}: {rejection.reason}")
            if rejection.jump_percent is not None:
                database.hold_quote(symbol, item.price, rejection.jump_percent, now)
            continue
        database.save_snapshot(
            Quote(
                symbol=symbol,
                asset_class=provider.asset_class,
                provider=provider.name,
                price=item.price,
                currency=currency,
                change_percent=item.change_percent,
                kind=provider.price_kind,
                price_time=item.price_time,
                fetched_at=now,
            ),
            item.series,
        )
        saved.append(symbol)

    detail = "; ".join(problems) or None
    outcome = "ok" if not problems else "partial" if saved else "error"
    database.record_attempt(provider.name, now, outcome, detail)
    return FetchResult(outcome, saved=tuple(saved), detail=detail)
