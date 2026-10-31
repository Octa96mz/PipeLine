import math

import pytest

from pipeline.db import Quote
from pipeline.providers.base import ProviderQuote
from pipeline.validate import MAX_CLOCK_SKEW_SECONDS, MAX_REFERENCE_AGE_SECONDS, rejection_reason
from synthetic import NOW


def new(price=100.0, change=1.0, price_time=NOW, series=((1, 1.0),)):
    return ProviderQuote("BTC", price, change, price_time, series)


def previous(price=100.0, currency="USD", fetched_at=NOW - 300):
    return Quote("BTC", "crypto", "synthetic", price, currency, 0.0, "live", fetched_at, fetched_at)


def reason(quote, reference=None, currency="USD"):
    rejection = rejection_reason(quote, reference, currency, max_jump_percent=50, now=NOW)
    return rejection.reason if rejection else None


def test_valid_quote_passes():
    assert reason(new(), previous()) is None


def test_first_quote_needs_no_reference():
    assert reason(new(price=1_000_000.0)) is None


@pytest.mark.parametrize("price", [0.0, -1.0, math.nan, math.inf])
def test_invalid_prices_are_rejected(price):
    assert reason(new(price=price)) == "precio no válido"


def test_non_finite_change_is_rejected():
    assert reason(new(change=math.inf)) == "variación no válida"


def test_unknown_change_is_allowed():
    assert reason(new(change=None)) is None


@pytest.mark.parametrize("value", [0.0, -1.0, math.nan])
def test_invalid_series_is_rejected(value):
    assert reason(new(series=((1, 1.0), (2, value)))) == "serie no válida"


def test_future_timestamp_is_rejected_beyond_clock_skew():
    assert reason(new(price_time=NOW + MAX_CLOCK_SKEW_SECONDS)) is None
    assert reason(new(price_time=NOW + MAX_CLOCK_SKEW_SECONDS + 1)) == "fecha futura"


@pytest.mark.parametrize("price", [151.0, 49.0, 100_000.0])
def test_absurd_jump_is_rejected(price):
    assert "salto" in reason(new(price=price), previous(price=100.0))


def test_jump_rejection_reports_its_size():
    rejection = rejection_reason(new(price=300.0), previous(), "USD", 50, NOW)
    assert rejection.jump_percent == 200.0


def test_other_rejections_are_not_reported_as_jumps():
    rejection = rejection_reason(new(price=-1.0), previous(), "USD", 50, NOW)
    assert rejection.jump_percent is None


@pytest.mark.parametrize("price", [150.0, 50.0])
def test_jump_at_the_limit_is_accepted(price):
    assert reason(new(price=price), previous(price=100.0)) is None


def test_old_reference_does_not_block_a_real_move_forever():
    reference = previous(fetched_at=NOW - MAX_REFERENCE_AGE_SECONDS - 1)
    assert reason(new(price=1000.0), reference) is None


def test_reference_in_another_currency_is_ignored():
    assert reason(new(price=1000.0), previous(currency="EUR"), currency="USD") is None
