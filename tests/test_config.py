from pathlib import Path

import pytest

from pipeline.config import Config, load_config, parse_config
from pipeline.errors import ConfigError

EXAMPLE = Path(__file__).parent.parent / "config.example.toml"


def test_missing_file_uses_defaults(tmp_path):
    assert load_config(tmp_path / "missing.toml") == Config()


def test_defaults_match_the_requested_setup():
    config = Config()
    assert config.display.currency == "USD"
    assert config.display.timezone == "Europe/Madrid"
    assert config.display.bar_items == ("BTC", "SPX")
    assert config.assets.crypto == ("BTC", "ETH", "XRP", "NEAR")
    assert config.assets.indices == ("SPX", "DJI", "IXIC", "IBEX")
    assert config.assets.stocks == ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA")


def test_example_file_documents_the_defaults():
    assert load_config(EXAMPLE) == Config()


def test_values_can_be_overridden(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[display]\ncurrency = "EUR"\nbar_items = ["ETH", "IBEX", "AAPL"]\n'
        '[assets]\nstocks = ["AAPL", "BRK.B"]\n'
        "[collector]\ncrypto_interval_minutes = 15\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.display.currency == "EUR"
    assert config.display.bar_items == ("ETH", "IBEX", "AAPL")
    assert config.assets.stocks == ("AAPL", "BRK.B")
    assert config.collector.crypto_interval_minutes == 15
    assert config.collector.max_retries == 3


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"unknown": {}}, "Secciones desconocidas"),
        ({"display": "x"}, "debe ser una tabla"),
        ({"display": {"typo": 1}}, "claves desconocidas"),
        ({"display": {"currency": "GBP"}}, "currency"),
        ({"display": {"timezone": "Marte/Olimpo"}}, "timezone"),
        ({"display": {"timezone": "../../etc/passwd"}}, "timezone"),
        ({"display": {"timezone": 5}}, "timezone"),
        ({"display": {"bar_items": []}}, "entre 1 y 3"),
        ({"display": {"bar_items": ["BTC", "ETH", "XRP", "NEAR"]}}, "entre 1 y 3"),
        ({"display": {"bar_items": ["DOGE"]}}, "no está en"),
        ({"display": {"bar_items": ["BTC", "BTC"]}}, "repetidos"),
        ({"assets": {"crypto": ["DOGE"]}}, "no admitidos"),
        ({"assets": {"indices": ["FTSE"]}}, "no admitidos"),
        ({"assets": {"stocks": "AAPL"}}, "lista"),
        ({"assets": {"stocks": ["aapl"]}}, "no válido"),
        ({"assets": {"stocks": ["A/../B"]}}, "no válido"),
        ({"assets": {"stocks": ["BTC"]}}, "repite"),
        ({"collector": {"crypto_interval_minutes": 1}}, "entre 2"),
        ({"collector": {"max_retries": True}}, "entero"),
        ({"collector": {"request_timeout_seconds": "5"}}, "entero"),
        ({"collector": {"eodhd_daily_call_budget": 21}}, "entre 0 y 20"),
        ({"validation": {"max_jump_percent": 0}}, "entre 1"),
    ],
)
def test_invalid_values_are_rejected(raw, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(raw)


def test_bar_items_must_follow_the_configured_assets():
    with pytest.raises(ConfigError, match="no está en"):
        parse_config({"assets": {"indices": ["DJI"]}})


def test_malformed_toml_is_reported(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[display\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="TOML no válido"):
        load_config(path)
