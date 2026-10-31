import socket
import sqlite3
import time
import urllib.error
import urllib.request

import pytest

from pipeline import cli, paths
from pipeline.db import Database
from pipeline.format import NBSP
from synthetic import NOW, FakeOpener, http_error, markets

HOUR = 3600


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


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)


def run_ok(opener, clock, *responses):
    opener.responses.extend(responses)
    return cli.main(["fetch", "--yes"])


def calls_made():
    with Database.open_readonly(paths.database_path()) as database:
        return database.calls_since("coingecko", 0)


def test_fetch_yes_saves_the_data(opener, clock, capsys):
    assert run_ok(opener, clock, markets()) == 0
    assert "actualizados BTC, ETH, XRP, NEAR" in capsys.readouterr().out
    assert calls_made() == 1


def test_manual_fetch_without_terminal_or_yes_makes_no_call(opener, clock, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert cli.main(["fetch"]) == 1
    assert "--yes" in capsys.readouterr().err
    assert opener.requests == []


def test_manual_fetch_warns_and_stops_if_declined(opener, clock, tty, monkeypatch, capsys):
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return "n"

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(["fetch"]) == 0
    assert "1 llamada" in prompts[0]
    assert "Hechas en las últimas 24 h: 0" in prompts[0]
    assert opener.requests == []


def test_manual_fetch_proceeds_if_confirmed(opener, clock, tty, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "s")
    opener.responses.append(markets())
    assert cli.main(["fetch"]) == 0
    assert len(opener.requests) == 1


def test_manual_fetch_during_cooldown_neither_asks_nor_calls(
    opener, clock, tty, monkeypatch, capsys
):
    run_ok(opener, clock, http_error(429, {"Retry-After": "900"}))
    capsys.readouterr()

    def fail(_prompt):
        raise AssertionError("no debe preguntar durante la pausa")

    monkeypatch.setattr("builtins.input", fail)
    clock["now"] += 60
    assert cli.main(["fetch"]) == 0
    assert "en pausa por 429" in capsys.readouterr().out
    assert len(opener.requests) == 1


def test_dry_run_makes_no_call_and_creates_nothing(opener, clock, capsys):
    assert cli.main(["fetch", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "1 llamada(s), hasta 4 con reintentos" in output
    assert "Simulación" in output
    assert opener.requests == []
    assert not paths.database_path().exists()


def test_scheduled_fetch_never_prompts_and_respects_the_interval(opener, clock, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    opener.responses.append(markets())
    assert cli.main(["fetch", "--scheduled"]) == 0
    clock["now"] += 60
    assert cli.main(["fetch", "--scheduled"]) == 0
    assert len(opener.requests) == 1


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (urllib.error.URLError("Network is unreachable"), "sin conexión"),
        (http_error(429, {"Retry-After": "900"}), "en pausa por 429"),
    ],
)
def test_no_network_or_429_is_not_a_collector_failure(opener, clock, capsys, failure, message):
    opener.responses.extend([failure] * 4)
    assert cli.main(["fetch", "--yes"]) == 0
    captured = capsys.readouterr()
    assert message in captured.out
    assert captured.err == ""


def test_provider_error_exits_non_zero(opener, clock, capsys):
    assert run_ok(opener, clock, b"not json") == 1
    assert "JSON" in capsys.readouterr().err


def test_status_without_any_fetch(clock, capsys):
    assert cli.main(["status"]) == 0
    output = capsys.readouterr().out
    assert "Powered by CoinGecko" in output
    assert "Llamadas hechas (24 h): 0" in output
    assert "BTC    sin datos" in output
    assert not paths.database_path().exists()


def test_status_shows_data_age_and_attribution(opener, clock, capsys):
    run_ok(opener, clock, markets())
    capsys.readouterr()
    clock["now"] += 300
    assert cli.main(["status"]) == 0
    output = capsys.readouterr().out
    assert "Powered by CoinGecko" in output
    assert f"1000,00{NBSP}$" in output
    assert f"+1,50{NBSP}%" in output
    assert "hace 5 min" in output
    assert "obsoleto" not in output


def test_status_reports_calls_without_inventing_a_limit(opener, clock, capsys):
    run_ok(opener, clock, markets())
    clock["now"] += 300
    run_ok(opener, clock, markets(updated=clock["now"]))
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    output = capsys.readouterr().out
    assert "Llamadas hechas (24 h): 2" in output
    assert "no publica un límite" in output
    assert "restantes" not in output


@pytest.mark.parametrize(
    ("failure", "label"),
    [
        (urllib.error.URLError("Network is unreachable"), "sin conexión"),
        (http_error(429, {"Retry-After": "900"}), "429"),
    ],
)
def test_status_marks_data_stale_after_a_failed_refresh(opener, clock, capsys, failure, label):
    run_ok(opener, clock, markets())
    clock["now"] += 300
    opener.responses.extend([failure] * 4)
    cli.main(["fetch", "--yes"])
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    output = capsys.readouterr().out
    assert label in output
    assert f"1000,00{NBSP}$" in output
    assert output.count("obsoleto") == 4


def test_status_shows_no_data_after_24_hours(opener, clock, capsys):
    run_ok(opener, clock, markets())
    capsys.readouterr()
    clock["now"] += 24 * HOUR + 1
    assert cli.main(["status"]) == 0
    output = capsys.readouterr().out
    assert "BTC    sin datos" in output
    assert "1000,00" not in output


def test_status_never_uses_the_network(opener, clock, monkeypatch, capsys):
    run_ok(opener, clock, markets())
    requests_before = len(opener.requests)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("status no puede abrir conexiones")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    assert cli.main(["status"]) == 0
    assert len(opener.requests) == requests_before


def test_status_does_not_modify_the_database(opener, clock, capsys):
    run_ok(opener, clock, markets())
    connection = sqlite3.connect(paths.database_path())
    before = connection.execute("SELECT COUNT(*) FROM fetch_attempts").fetchone()
    connection.close()
    clock["now"] += 24 * HOUR + 1
    cli.main(["status"])
    connection = sqlite3.connect(paths.database_path())
    assert connection.execute("SELECT COUNT(*) FROM fetch_attempts").fetchone() == before
    assert connection.execute("SELECT COUNT(*) FROM quotes").fetchone() == (4,)
    connection.close()


def test_invalid_config_is_reported(clock, capsys):
    paths.config_path().parent.mkdir(parents=True)
    paths.config_path().write_text('[display]\ncurrency = "GBP"\n', encoding="utf-8")
    assert cli.main(["status"]) == 1
    assert "currency" in capsys.readouterr().err
