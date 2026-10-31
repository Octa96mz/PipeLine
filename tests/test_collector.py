import dataclasses
import urllib.error

import pytest

from pipeline.collector import fetch_lock, run_fetch
from pipeline.config import Config
from pipeline.db import Database
from pipeline.errors import FetchInProgress
from pipeline.freshness import EXPIRED, FRESH, STALE, freshness
from pipeline.http import HttpClient
from pipeline.providers.coingecko import CoinGecko
from synthetic import NOW, FakeOpener, coin, http_error, markets

SYMBOLS = ("BTC", "ETH", "XRP", "NEAR")
PROVIDER = CoinGecko()
STALE_AFTER = 1800
RETENTION = PROVIDER.retention_seconds


@pytest.fixture
def database(tmp_path):
    with Database.open(tmp_path / "pipeline.db") as opened:
        yield opened


def run(database, opener, now=NOW, scheduled=False, config=None, retries=0):
    client = HttpClient(
        on_request=lambda: database.record_api_call(PROVIDER.name, now),
        timeout=1,
        max_retries=retries,
        opener=opener,
        sleep=lambda _: None,
    )
    return run_fetch(database, PROVIDER, SYMBOLS, config or Config(), client, now, scheduled)


def state(database, symbol, now):
    return freshness(
        database.quote(symbol),
        now,
        STALE_AFTER,
        RETENTION,
        database.last_attempt(PROVIDER.name),
    )


def test_successful_fetch_saves_everything(database):
    result = run(database, FakeOpener(markets()))
    assert result.status == "ok"
    assert result.saved == SYMBOLS
    quote = database.quote("BTC")
    assert quote.price == 1000.0
    assert quote.currency == "USD"
    assert quote.kind == "live"
    assert quote.asset_class == "crypto"
    assert quote.fetched_at == NOW
    assert len(database.series("BTC")) == 3
    assert state(database, "BTC", NOW) == FRESH
    assert database.calls_since(PROVIDER.name, NOW) == 1


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (urllib.error.URLError("Network is unreachable"), "offline"),
        (TimeoutError("timed out"), "offline"),
        (urllib.error.URLError("Temporary failure in name resolution"), "offline"),
        (http_error(429, {"Retry-After": "300"}), "rate_limited"),
    ],
)
def test_no_network_or_429_keeps_old_data_and_marks_it_stale(database, failure, status):
    run(database, FakeOpener(markets()))
    assert state(database, "BTC", NOW) == FRESH

    later = NOW + 300
    result = run(database, FakeOpener(failure), now=later)

    assert result.status == status
    for symbol in SYMBOLS:
        assert database.quote(symbol).fetched_at == NOW
        assert len(database.series(symbol)) == 3
        # Solo 5 minutos después: lo marca el fallo, no la edad del dato.
        assert state(database, symbol, later) == STALE
    assert database.last_attempt(PROVIDER.name).outcome == status


def test_a_later_success_clears_the_stale_mark(database):
    run(database, FakeOpener(markets()))
    run(database, FakeOpener(urllib.error.URLError("down")), now=NOW + 300)
    assert state(database, "BTC", NOW + 300) == STALE
    run(database, FakeOpener(markets(updated=NOW + 600)), now=NOW + 600)
    assert state(database, "BTC", NOW + 600) == FRESH


def test_429_sets_a_cooldown_that_blocks_further_calls(database):
    run(database, FakeOpener(http_error(429, {"Retry-After": "900"})))
    assert database.cooldown_until(PROVIDER.name) == NOW + 900

    for now in (NOW + 300, NOW + 899):
        for scheduled in (True, False):
            opener = FakeOpener()
            result = run(database, opener, now=now, scheduled=scheduled)
            assert result.status == "cooldown"
            assert result.cooldown_until == NOW + 900
            assert opener.requests == []
    assert database.calls_since(PROVIDER.name, 0) == 1


def test_429_makes_exactly_one_request_even_with_retries_configured(database):
    opener = FakeOpener(http_error(429), markets())
    run(database, opener, retries=3)
    assert len(opener.requests) == 1


def test_fetch_resumes_when_the_cooldown_ends(database):
    run(database, FakeOpener(http_error(429, {"Retry-After": "900"})))
    assert run(database, FakeOpener(markets()), now=NOW + 900).status == "ok"


def test_provider_error_is_recorded_and_keeps_old_data(database):
    run(database, FakeOpener(markets()))
    result = run(database, FakeOpener(http_error(500)), now=NOW + 300)
    assert result.status == "error"
    assert database.quote("BTC").fetched_at == NOW
    assert state(database, "BTC", NOW + 300) == STALE


def test_data_older_than_24_hours_is_expired_when_read(database):
    run(database, FakeOpener(markets()))
    assert state(database, "BTC", NOW + RETENTION) == STALE
    assert state(database, "BTC", NOW + RETENTION + 1) == EXPIRED


def test_data_older_than_24_hours_is_deleted_even_without_network(database):
    run(database, FakeOpener(markets()))
    later = NOW + RETENTION + 1
    result = run(database, FakeOpener(urllib.error.URLError("down")), now=later)
    assert result.status == "offline"
    assert database.quote("BTC") is None
    assert database.series("BTC") == []


def test_data_exactly_at_the_limit_is_kept(database):
    run(database, FakeOpener(markets()))
    run(database, FakeOpener(urllib.error.URLError("down")), now=NOW + RETENTION)
    assert database.quote("BTC") is not None


def test_scheduled_run_waits_for_the_interval(database):
    run(database, FakeOpener(markets()), scheduled=True)
    opener = FakeOpener()
    assert run(database, opener, now=NOW + 60, scheduled=True).status == "not_due"
    assert opener.requests == []


def test_scheduled_run_tolerates_timer_jitter(database):
    run(database, FakeOpener(markets()), scheduled=True)
    result = run(database, FakeOpener(markets()), now=NOW + 280, scheduled=True)
    assert result.status == "ok"


def test_scheduled_run_does_not_speed_up_after_a_failure(database):
    run(database, FakeOpener(urllib.error.URLError("down")), scheduled=True)
    opener = FakeOpener()
    assert run(database, opener, now=NOW + 60, scheduled=True).status == "not_due"
    assert opener.requests == []


def test_manual_run_ignores_the_interval(database):
    run(database, FakeOpener(markets()))
    assert run(database, FakeOpener(markets()), now=NOW + 60).status == "ok"


def test_rejected_symbol_keeps_its_old_value_and_goes_stale(database):
    run(database, FakeOpener(markets()))
    later = NOW + 300
    response = [*markets(("ETH", "XRP", "NEAR"), updated=later), coin("BTC", price=99_999.0)]
    result = run(database, FakeOpener(response), now=later)

    assert result.status == "partial"
    assert set(result.saved) == {"ETH", "XRP", "NEAR"}
    assert "BTC: salto" in result.detail
    assert database.quote("BTC").price == 1000.0
    assert state(database, "BTC", later) == STALE
    assert state(database, "ETH", later) == FRESH


def test_symbol_missing_from_the_response_is_partial(database):
    result = run(database, FakeOpener(markets(("BTC", "ETH", "XRP"))))
    assert result.status == "partial"
    assert "NEAR: sin dato" in result.detail


def test_all_symbols_rejected_is_an_error(database):
    result = run(database, FakeOpener([coin(symbol, price=-1.0) for symbol in SYMBOLS]))
    assert result.status == "error"
    assert result.saved == ()
    assert database.quote("BTC") is None


def test_currency_comes_from_the_config(database):
    display = dataclasses.replace(Config().display, currency="EUR")
    config = dataclasses.replace(Config(), display=display)
    run(database, FakeOpener(markets()), config=config)
    assert database.quote("BTC").currency == "EUR"


def test_old_logs_are_pruned(database):
    database.record_api_call(PROVIDER.name, NOW - 31 * 86_400)
    database.record_attempt(PROVIDER.name, NOW - 31 * 86_400, "ok")
    run(database, FakeOpener(markets()))
    assert database.calls_since(PROVIDER.name, 0) == 1
    assert database.last_attempt(PROVIDER.name).finished_at == NOW


def test_lock_prevents_a_second_fetch(tmp_path):
    path = tmp_path / "data" / "fetch.lock"
    with fetch_lock(path), pytest.raises(FetchInProgress), fetch_lock(path):
        pass
    with fetch_lock(path):
        pass
