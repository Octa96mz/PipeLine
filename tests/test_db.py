import sqlite3
import stat

import pytest

from pipeline.db import Database, Quote
from pipeline.errors import DatabaseError


def make_quote(**overrides):
    values = {
        "symbol": "BTC",
        "asset_class": "crypto",
        "provider": "synthetic",
        "price": 100.0,
        "currency": "USD",
        "change_percent": 1.5,
        "kind": "live",
        "price_time": 1000,
        "fetched_at": 1010,
    }
    return Quote(**{**values, **overrides})


@pytest.fixture
def path(tmp_path):
    return tmp_path / "data" / "pipeline.db"


@pytest.fixture
def database(path):
    with Database.open(path) as opened:
        yield opened


def test_new_database_is_private(database, path):
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_migrations_run_once(path):
    with Database.open(path) as first:
        version = first.schema_version()
        first.save_snapshot(make_quote(), [])
    assert version == 1
    with Database.open(path) as second:
        assert second.schema_version() == version
        assert second.quote("BTC") == make_quote()


def test_newer_schema_is_refused_instead_of_being_altered(path):
    Database.open(path).close()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    with pytest.raises(DatabaseError, match="más reciente"):
        Database.open(path)
    with pytest.raises(DatabaseError, match="más reciente"):
        Database.open_readonly(path)


def test_failed_migration_leaves_the_database_unchanged(path, monkeypatch):
    monkeypatch.setattr(
        "pipeline.db._MIGRATIONS", ("CREATE TABLE ok (id INTEGER); CREATE TABLE broken (;",)
    )
    with pytest.raises(DatabaseError):
        Database.open(path)
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
    connection.close()


def test_snapshot_round_trip(database):
    quote = make_quote(currency=None, asset_class="index", symbol="SPX", kind="close")
    database.save_snapshot(quote, [(2, 20.0), (1, 10.0)])
    assert database.quote("SPX") == quote
    assert database.series("SPX") == [(1, 10.0), (2, 20.0)]


def test_snapshot_replaces_previous_series(database):
    database.save_snapshot(make_quote(price=100.0), [(1, 10.0), (2, 20.0)])
    database.save_snapshot(make_quote(price=200.0), [(3, 30.0)])
    assert database.quote("BTC").price == 200.0
    assert database.series("BTC") == [(3, 30.0)]


@pytest.mark.parametrize("price", [0.0, -1.0])
def test_non_positive_price_is_rejected(database, price):
    with pytest.raises(sqlite3.IntegrityError):
        database.save_snapshot(make_quote(price=price), [])
    assert database.quote("BTC") is None


def test_invalid_series_keeps_the_previous_snapshot(database):
    database.save_snapshot(make_quote(price=100.0), [(1, 10.0)])
    with pytest.raises(sqlite3.IntegrityError):
        database.save_snapshot(make_quote(price=200.0), [(2, -5.0)])
    assert database.quote("BTC").price == 100.0
    assert database.series("BTC") == [(1, 10.0)]


def test_unknown_symbol_returns_nothing(database):
    assert database.quote("NOPE") is None
    assert database.series("NOPE") == []


def test_quota_counts_only_the_last_24_hours(database):
    now = 200_000
    database.record_api_call("synthetic", now - 86_401)
    database.record_api_call("synthetic", now - 86_400)
    database.record_api_call("synthetic", now)
    database.record_api_call("other", now)
    assert database.remaining_calls("synthetic", budget=18, now=now) == 16


def test_quota_never_goes_negative(database):
    for _ in range(3):
        database.record_api_call("synthetic", 100)
    assert database.remaining_calls("synthetic", budget=2, now=100) == 0


def test_last_attempt_is_the_most_recent(database):
    assert database.last_attempt("synthetic") is None
    database.record_attempt("synthetic", 10, "error", "timeout")
    database.record_attempt("synthetic", 20, "ok")
    attempt = database.last_attempt("synthetic")
    assert (attempt.finished_at, attempt.outcome, attempt.detail) == (20, "ok", None)


def test_attempt_detail_never_stores_a_key(database):
    secret = "synthetic-secret-value"
    database.record_attempt(
        "synthetic", 10, "error", f"HTTP 500 https://example.test/eod?api_token={secret}&fmt=json"
    )
    detail = database.last_attempt("synthetic").detail
    assert secret not in detail
    assert "fmt=json" in detail


def test_readonly_reads_but_cannot_write(database, path):
    database.save_snapshot(make_quote(), [(1, 10.0)])
    with Database.open_readonly(path) as reader:
        assert reader.quote("BTC") == make_quote()
        with pytest.raises(sqlite3.OperationalError):
            reader.record_api_call("synthetic", 1)


def test_readonly_does_not_create_a_missing_database(path):
    with pytest.raises(DatabaseError):
        Database.open_readonly(path)
    assert not path.exists()


def test_readonly_handles_paths_with_special_characters(tmp_path):
    path = tmp_path / "dir with spaces?#" / "pipeline.db"
    Database.open(path).close()
    with Database.open_readonly(path) as reader:
        assert reader.schema_version() == 1


def test_corrupt_file_is_reported(path):
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not a sqlite database, only synthetic bytes" * 100)
    with pytest.raises(DatabaseError):
        Database.open(path)
