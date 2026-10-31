import pytest

from pipeline.format import (
    NBSP,
    format_age,
    format_clock,
    format_number,
    format_percent,
    format_price,
)


@pytest.mark.parametrize(
    ("value", "decimals", "expected"),
    [
        (77386.0, 2, "77.386,00"),
        (1234567.5, 2, "1.234.567,50"),
        (2244.74, 2, "2244,74"),
        (-12345.5, 1, "-12.345,5"),
        (0.5, 2, "0,50"),
        (7744.0, 0, "7744"),
    ],
)
def test_format_number(value, decimals, expected):
    assert format_number(value, decimals) == expected


@pytest.mark.parametrize(
    ("value", "currency", "expected"),
    [
        (77386.0, "USD", f"77.386,00{NBSP}$"),
        (1.25, "USD", f"1,25{NBSP}$"),
        (0.5, "EUR", f"0,5000{NBSP}€"),
        (0.00123, "USD", f"0,001230{NBSP}$"),
        (15000.0, None, "15.000,00"),
    ],
)
def test_format_price(value, currency, expected):
    assert format_price(value, currency) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1.5, f"+1,50{NBSP}%"), (-0.38, f"-0,38{NBSP}%"), (0.0, f"+0,00{NBSP}%")],
)
def test_format_percent(value, expected):
    assert format_percent(value) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "ahora"),
        (59, "ahora"),
        (60, "hace 1 min"),
        (3599, "hace 59 min"),
        (3600, "hace 1 h"),
        (86_399, "hace 23 h"),
        (86_400, "hace 1 d"),
    ],
)
def test_format_age(seconds, expected):
    assert format_age(seconds) == expected


def test_format_clock_uses_the_configured_timezone():
    # 2026-07-01 12:00 UTC: verano en Madrid (UTC+2).
    assert format_clock(1_782_907_200, "Europe/Madrid") == "14:00"
    # 2026-01-15 12:00 UTC: invierno en Madrid (UTC+1).
    assert format_clock(1_768_478_400, "Europe/Madrid") == "13:00"
