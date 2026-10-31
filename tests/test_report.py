import json
import subprocess
import sys
import time
import urllib.error

import pytest

from pipeline import cli, paths
from pipeline.format import NBSP
from pipeline.report import MAX_SERIES_POINTS, SCHEMA_VERSION
from synthetic import NOW, FakeOpener, coin, http_error, markets

TOP_LEVEL_KEYS = {
    "schema_version",
    "generated_at",
    "status",
    "error",
    "currency",
    "timezone",
    "bar",
    "groups",
    "providers",
}
ROW_KEYS = {
    "symbol",
    "name",
    "short_name",
    "asset_class",
    "state",
    "state_label",
    "stale",
    "reason",
    "provider",
    "price",
    "price_text",
    "compact_text",
    "currency",
    "change_percent",
    "change_text",
    "direction",
    "kind",
    "price_time",
    "fetched_at",
    "age_seconds",
    "age_text",
    "series",
    "hold",
}
PROVIDER_KEYS = {
    "id",
    "name",
    "attribution",
    "calls_24h",
    "calls_limit",
    "calls_remaining",
    "last_attempt",
    "cooldown_until",
    "cooldown_until_text",
    "offline_streak",
    "next_attempt_at",
    "next_attempt_text",
}
UNREACHABLE = urllib.error.URLError(OSError(101, "Network is unreachable"))


@pytest.fixture
def clock(monkeypatch):
    current = {"now": NOW}
    monkeypatch.setattr(cli, "_now", lambda: current["now"])
    return current


@pytest.fixture
def opener(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    instance = FakeOpener()
    monkeypatch.setattr("pipeline.http._build_opener", lambda: instance)
    return instance


def fetch(opener, *responses):
    opener.responses.extend(responses)
    return cli.main(["fetch", "--yes"])


def read_json(capsys, expected_code=0):
    capsys.readouterr()
    assert cli.main(["json"]) == expected_code
    captured = capsys.readouterr()
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def rows_by_symbol(report):
    return {row["symbol"]: row for group in report["groups"] for row in group["items"]}


def test_schema_without_any_data(clock, capsys):
    report = read_json(capsys)
    assert set(report) == TOP_LEVEL_KEYS
    assert report["schema_version"] == SCHEMA_VERSION == 1
    assert report["generated_at"] == NOW
    assert report["status"] == "no_data"
    assert report["error"] is None
    assert report["currency"] == "USD"
    assert report["timezone"] == "Europe/Madrid"
    assert [group["id"] for group in report["groups"]] == ["crypto", "indices", "stocks"]
    for row in rows_by_symbol(report).values():
        assert set(row) == ROW_KEYS
    assert set(report["providers"][0]) == PROVIDER_KEYS
    assert not paths.database_path().exists()


def test_indices_and_stocks_are_unavailable(opener, clock, capsys):
    fetch(opener, markets())
    report = read_json(capsys)
    indices, stocks = report["groups"][1]["items"], report["groups"][2]["items"]
    assert [row["symbol"] for row in indices] == ["SPX", "DJI", "IXIC", "IBEX"]
    assert [row["symbol"] for row in stocks] == [
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "META",
        "TSLA",
    ]
    for row in [*indices, *stocks]:
        assert row["state"] == "unavailable"
        assert row["state_label"] == "no disponible"
        assert row["price"] is None
        assert row["stale"] is False
        assert row["reason"] == "Sin proveedor configurado"
    assert {row["asset_class"] for row in indices} == {"index"}
    assert {row["asset_class"] for row in stocks} == {"stock"}


def test_unavailable_rows_do_not_make_the_report_stale(opener, clock, capsys):
    fetch(opener, markets())
    assert read_json(capsys)["status"] == "fresh"


def test_fresh_row_has_values_and_spanish_formatting(opener, clock, capsys):
    fetch(opener, [coin("BTC", price=77386.5, change=-0.5), *markets(("ETH", "XRP", "NEAR"))])
    clock["now"] += 120
    row = rows_by_symbol(read_json(capsys))["BTC"]
    assert row["name"] == "Bitcoin"
    assert row["state"] == "fresh"
    assert row["stale"] is False
    assert row["reason"] is None
    assert row["price"] == 77386.5
    assert row["price_text"] == f"77.386,50{NBSP}$"
    assert row["compact_text"] == "77.386"
    assert row["currency"] == "USD"
    assert row["change_text"] == f"-0,50{NBSP}%"
    assert row["direction"] == "down"
    assert row["kind"] == "live"
    assert row["provider"] == "coingecko"
    assert row["age_seconds"] == 120
    assert row["age_text"] == row["state_label"] == "hace 2 min"
    assert row["series"] == [1.0, 2.0, 3.0]


@pytest.mark.parametrize(
    ("change", "direction"), [(1.0, "up"), (-1.0, "down"), (0.0, "flat"), (None, None)]
)
def test_direction(opener, clock, capsys, change, direction):
    fetch(opener, [coin("BTC", change=change), *markets(("ETH", "XRP", "NEAR"))])
    assert rows_by_symbol(read_json(capsys))["BTC"]["direction"] == direction


def test_series_is_bounded(opener, clock, capsys):
    long_series = [float(index + 1) for index in range(168)]
    fetch(opener, [coin("BTC", sparkline=long_series), *markets(("ETH", "XRP", "NEAR"))])
    series = rows_by_symbol(read_json(capsys))["BTC"]["series"]
    assert len(series) == MAX_SERIES_POINTS
    assert (series[0], series[-1]) == (1.0, 168.0)


def test_default_bar_shows_btc_and_an_unavailable_sp500(opener, clock, capsys):
    fetch(opener, markets())
    bar = read_json(capsys)["bar"]
    assert [item["symbol"] for item in bar["items"]] == ["BTC", "SPX"]
    btc, spx = bar["items"]
    assert (btc["label"], btc["value_text"], btc["direction"], btc["state"]) == (
        "BTC",
        "1000",
        "up",
        "fresh",
    )
    assert (spx["label"], spx["value_text"], spx["direction"], spx["state"]) == (
        "S&P",
        "—",
        None,
        "unavailable",
    )


def test_bar_tooltip_has_the_update_time_and_attribution(opener, clock, capsys):
    fetch(opener, markets())
    clock["now"] += 300
    bar = read_json(capsys)["bar"]
    assert bar["updated_at"] == NOW
    # NOW es 2027-01-15 08:00 UTC: 09:00 en Madrid.
    assert "Última actualización: 09:00 (hace 5 min)" in bar["tooltip"]
    assert "Powered by CoinGecko" in bar["tooltip"]


def test_provider_block_has_attribution_and_calls_without_a_limit(opener, clock, capsys):
    fetch(opener, markets())
    provider = read_json(capsys)["providers"][0]
    assert provider["attribution"] == "Powered by CoinGecko"
    assert provider["calls_24h"] == 1
    assert provider["calls_limit"] is None
    assert provider["calls_remaining"] is None
    assert provider["last_attempt"]["outcome"] == "ok"


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (UNREACHABLE, "Sin conexión"),
        (urllib.error.URLError(OSError(1, "Operation not permitted")), "Sin conexión"),
        (TimeoutError("timed out"), "Sin conexión"),
        (http_error(429, {"Retry-After": "900"}), "El proveedor pide esperar"),
    ],
)
def test_no_network_kill_switch_or_429_show_stale_data(opener, clock, capsys, failure, reason):
    fetch(opener, markets())
    clock["now"] += 300
    fetch(opener, *[failure] * 4)
    report = read_json(capsys)
    assert report["status"] == "stale"
    btc = rows_by_symbol(report)["BTC"]
    assert btc["state"] == "stale"
    assert btc["state_label"] == "obsoleto"
    assert btc["stale"] is True
    assert btc["reason"] == reason
    assert btc["price"] == 1000.0
    assert btc["age_text"] == "hace 5 min"
    assert "Datos obsoletos" in report["bar"]["tooltip"]
    assert reason in report["bar"]["tooltip"]


def test_kill_switch_makes_no_counted_calls_and_json_still_answers(opener, clock, capsys):
    fetch(opener, markets())
    clock["now"] += 300
    kill_switch = urllib.error.URLError(OSError(1, "Operation not permitted"))
    fetch(opener, *[kill_switch] * 4)
    provider = read_json(capsys)["providers"][0]
    assert provider["calls_24h"] == 1
    assert provider["offline_streak"] == 1


def test_old_data_goes_stale_by_age_alone(opener, clock, capsys):
    fetch(opener, markets())
    clock["now"] += 1801
    row = rows_by_symbol(read_json(capsys))["BTC"]
    assert row["state"] == "stale"
    assert row["reason"] == "Dato antiguo"


def test_data_older_than_24_hours_shows_no_values(opener, clock, capsys):
    fetch(opener, markets())
    clock["now"] += 86_401
    report = read_json(capsys)
    btc = rows_by_symbol(report)["BTC"]
    assert report["status"] == "no_data"
    assert btc["state"] == "no_data"
    assert btc["state_label"] == "sin datos"
    assert btc["price"] is None
    assert btc["series"] == []
    assert report["bar"]["items"][0]["value_text"] == "—"


def held_fetch(opener, clock):
    fetch(opener, markets())
    clock["now"] += 300
    fetch(opener, [coin("BTC", price=3000.0), *markets(("ETH", "XRP", "NEAR"))])


def test_jump_hold_is_explained_in_json(opener, clock, capsys):
    held_fetch(opener, clock)
    report = read_json(capsys)
    rows = rows_by_symbol(report)
    btc = rows["BTC"]
    assert report["status"] == "stale"
    assert btc["state"] == "held"
    assert btc["state_label"] == "retenido"
    assert btc["stale"] is True
    assert btc["price"] == 1000.0
    assert btc["hold"]["rejected_price"] == 3000.0
    assert btc["hold"]["rejected_price_text"] == f"3000,00{NBSP}$"
    assert btc["hold"]["jump_percent"] == 200.0
    assert btc["hold"]["since"] == NOW + 300
    assert "salto del 200 %" in btc["reason"]
    assert rows["ETH"]["hold"] is None
    assert report["bar"]["items"][0]["state"] == "held"
    assert "salto del 200 %" in report["bar"]["tooltip"]


def test_jump_hold_is_explained_in_status_and_show(opener, clock, capsys):
    held_fetch(opener, clock)
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    assert "retenido" in capsys.readouterr().out
    assert cli.main(["show"]) == 0
    assert "salto del 200 %" in capsys.readouterr().out


def test_status_shows_offline_backoff(opener, clock, capsys):
    fetch(opener, *[UNREACHABLE] * 4)
    clock["now"] += 300
    fetch(opener, *[UNREACHABLE] * 4)
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    output = capsys.readouterr().out
    assert "Sin conexión en 2 pasadas seguidas" in output
    assert "Llamadas hechas (24 h): 0" in output


def test_show_lists_every_group(opener, clock, capsys):
    fetch(opener, markets())
    capsys.readouterr()
    assert cli.main(["show"]) == 0
    output = capsys.readouterr().out
    for expected in ("Cripto", "Índices", "Acciones", "S&P 500", "no disponible", "Bitcoin"):
        assert expected in output
    assert "▁▅█" in output
    assert "Powered by CoinGecko" in output


def test_pretty_output_is_the_same_data(opener, clock, capsys):
    fetch(opener, markets())
    compact = read_json(capsys)
    assert cli.main(["json", "--pretty"]) == 0
    assert json.loads(capsys.readouterr().out) == compact


def test_invalid_config_still_prints_valid_json(clock, capsys):
    paths.config_path().parent.mkdir(parents=True)
    paths.config_path().write_text('[display]\ncurrency = "GBP"\n', encoding="utf-8")
    report = read_json(capsys, expected_code=1)
    assert set(report) == TOP_LEVEL_KEYS
    assert report["status"] == "error"
    assert "currency" in report["error"]
    assert report["groups"] == []
    assert "currency" in report["bar"]["tooltip"]


def test_corrupt_database_still_prints_valid_json(clock, capsys):
    paths.database_path().parent.mkdir(parents=True)
    paths.database_path().write_bytes(b"synthetic garbage, not a database" * 100)
    report = read_json(capsys, expected_code=1)
    assert report["status"] == "error"
    assert report["error"]


def test_json_output_is_strict(opener, clock, capsys):
    fetch(opener, markets())
    capsys.readouterr()
    cli.main(["json"])

    def refuse(name):
        raise AssertionError(f"Constante no estándar: {name}")

    json.loads(capsys.readouterr().out, parse_constant=refuse)


@pytest.mark.parametrize("command", ["json", "status", "show"])
def test_readers_never_load_network_code(command, tmp_path):
    # En un proceso aparte: garantiza que estos comandos no pueden llamar a ninguna API.
    script = (
        "import sys\n"
        "from pipeline.cli import main\n"
        f"code = main([{command!r}])\n"
        "loaded = {'urllib.request', 'http.client', 'ssl', 'socket'} & set(sys.modules)\n"
        "assert not loaded, loaded\n"
        "assert 'pipeline.http' not in sys.modules\n"
        "sys.exit(code)\n"
    )
    environment = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
