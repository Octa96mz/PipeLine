import logging

import pytest

from pipeline.redact import REDACTED, RedactingFormatter, redact_text

SECRET = "synthetic-secret-value"


@pytest.mark.parametrize(
    "template",
    [
        "https://example.test/api/eod/AAPL.US?api_token={}&fmt=json",
        "https://example.test/q?fmt=json&API_TOKEN={}",
        "https://example.test/q?apikey={}",
        "https://example.test/q?api_key={}#fragment",
        "https://example.test/q?token={}",
        "https://example.test/q?key={}",
        "https://example.test/q?x_cg_demo_api_key={}",
        "https://example.test/q?x_cg_pro_api_key={}",
        "x-cg-demo-api-key: {}",
        "x-cg-pro-api-key: {}",
        "Authorization: {}",
        "HTTP Error 403 for url 'https://example.test/?api_token={}'",
    ],
)
def test_secret_is_removed(template):
    result = redact_text(template.format(SECRET))
    assert SECRET not in result
    assert REDACTED in result


def test_other_parameters_are_kept():
    url = f"https://example.test/api/eod/AAPL.US?api_token={SECRET}&fmt=json&period=d"
    assert redact_text(url) == (
        f"https://example.test/api/eod/AAPL.US?api_token={REDACTED}&fmt=json&period=d"
    )


def test_unrelated_text_is_unchanged():
    text = "monkey=banana https://example.test/?vs_currency=usd&ids=bitcoin"
    assert redact_text(text) == text


def _format(record):
    return RedactingFormatter("%(message)s").format(record)


def test_log_message_arguments_are_redacted():
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        "fallo en %s",
        (f"https://x.test/?apikey={SECRET}",),
        None,
    )
    assert SECRET not in _format(record)


def test_exception_traceback_is_redacted():
    try:
        raise ValueError(f"https://x.test/?api_token={SECRET}")
    except ValueError as error:
        record = logging.LogRecord(
            "test",
            logging.ERROR,
            __file__,
            1,
            "fallo",
            None,
            (ValueError, error, error.__traceback__),
        )
    output = _format(record)
    assert "ValueError" in output
    assert SECRET not in output
