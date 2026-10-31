from urllib.parse import parse_qs, urlparse

import pytest

from pipeline.errors import ProviderError, RateLimited
from pipeline.http import HttpClient
from pipeline.providers.coingecko import SPARKLINE_SPAN_SECONDS, CoinGecko
from synthetic import NOW, FakeOpener, coin, http_error, markets

SYMBOLS = ("BTC", "ETH", "XRP", "NEAR")


def fetch(response, symbols=SYMBOLS, currency="USD"):
    opener = FakeOpener(response)
    client = HttpClient(
        on_request=lambda: None, timeout=1, max_retries=0, opener=opener, sleep=lambda _: None
    )
    return CoinGecko().fetch(symbols, currency, client), opener


def by_symbol(quotes):
    return {quote.symbol: quote for quote in quotes}


def test_request_asks_for_all_coins_in_one_call():
    _, opener = fetch(markets())
    assert len(opener.requests) == 1
    url = urlparse(opener.requests[0].full_url)
    query = parse_qs(url.query)
    assert url.scheme == "https"
    assert url.netloc == "api.coingecko.com"
    assert url.path == "/api/v3/coins/markets"
    assert query["vs_currency"] == ["usd"]
    assert query["ids"] == ["bitcoin,ethereum,ripple,near"]
    assert query["sparkline"] == ["true"]
    assert query["price_change_percentage"] == ["24h"]


def test_currency_is_sent_to_the_provider():
    _, opener = fetch(markets(), currency="EUR")
    assert parse_qs(urlparse(opener.requests[0].full_url).query)["vs_currency"] == ["eur"]


def test_parses_all_requested_coins():
    quotes = by_symbol(fetch(markets())[0])
    assert set(quotes) == set(SYMBOLS)
    assert quotes["NEAR"].price == 5.0
    assert quotes["BTC"].change_percent == 1.5
    assert quotes["BTC"].price_time == NOW


def test_sparkline_spans_seven_days_and_ends_at_the_update_time():
    quotes = by_symbol(fetch([coin("BTC", sparkline=(1.0, 2.0, 3.0))], symbols=("BTC",))[0])
    assert quotes["BTC"].series == (
        (NOW - SPARKLINE_SPAN_SECONDS, 1.0),
        (NOW - SPARKLINE_SPAN_SECONDS // 2, 2.0),
        (NOW, 3.0),
    )


def test_gaps_in_the_sparkline_are_dropped():
    quote = fetch([coin("BTC", sparkline=(1.0, None, 3.0))], symbols=("BTC",))[0][0]
    assert [value for _, value in quote.series] == [1.0, 3.0]


@pytest.mark.parametrize("sparkline", [(), (1.0,)])
def test_too_short_sparkline_gives_an_empty_series(sparkline):
    quote = fetch([coin("BTC", sparkline=sparkline)], symbols=("BTC",))[0][0]
    assert quote.series == ()


def test_missing_change_is_kept_as_unknown():
    quote = fetch([coin("BTC", change=None)], symbols=("BTC",))[0][0]
    assert quote.change_percent is None


@pytest.mark.parametrize(
    "broken",
    [
        {**coin("BTC"), "current_price": None},
        {**coin("BTC"), "current_price": "1000"},
        {**coin("BTC"), "current_price": True},
        {**coin("BTC"), "last_updated": "yesterday"},
        {**coin("BTC"), "last_updated": None},
        {**coin("BTC"), "last_updated": "2030-01-01T00:00:00"},
        {**coin("BTC"), "id": "unrequested-coin"},
        "not an object",
    ],
)
def test_malformed_items_are_omitted_without_losing_the_rest(broken):
    quotes = by_symbol(fetch([broken, coin("ETH")])[0])
    assert set(quotes) == {"ETH"}


@pytest.mark.parametrize("payload", [{"status": {"error_code": 1}}, "text", None])
def test_unexpected_payload_is_an_error(payload):
    with pytest.raises(ProviderError, match="lista"):
        fetch(payload)


def test_rate_limit_reaches_the_caller():
    with pytest.raises(RateLimited):
        fetch(http_error(429))


def test_declares_the_required_attribution_and_retention():
    provider = CoinGecko()
    assert provider.attribution == "Powered by CoinGecko"
    assert provider.retention_seconds == 86_400
    assert provider.request_count(SYMBOLS) == 1
