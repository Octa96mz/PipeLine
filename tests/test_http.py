import urllib.error
from email.utils import formatdate

import pytest

from pipeline.errors import NetworkError, ProviderError, RateLimited
from pipeline.http import (
    DEFAULT_COOLDOWN_SECONDS,
    MAX_COOLDOWN_SECONDS,
    MAX_RESPONSE_BYTES,
    MIN_COOLDOWN_SECONDS,
    HttpClient,
    parse_retry_after,
)
from synthetic import FakeOpener, http_error

URL = "https://example.test/data"
SECRET = "synthetic-secret-value"


def make_client(opener, max_retries=3):
    sleeps = []
    calls = []
    client = HttpClient(
        on_request=lambda: calls.append(1),
        timeout=7,
        max_retries=max_retries,
        opener=opener,
        sleep=sleeps.append,
    )
    return client, calls, sleeps


def test_success_uses_the_configured_timeout():
    opener = FakeOpener({"ok": True})
    client, calls, sleeps = make_client(opener)
    assert client.get_json(URL) == {"ok": True}
    assert opener.timeouts == [7]
    assert len(calls) == 1
    assert sleeps == []


def test_network_failures_retry_with_backoff_and_count_every_call():
    failure = urllib.error.URLError("unreachable")
    client, calls, sleeps = make_client(FakeOpener(failure, failure, failure, failure))
    with pytest.raises(NetworkError):
        client.get_json(URL)
    assert len(calls) == 4
    assert sleeps == [1, 2, 4]


def test_timeout_is_a_network_failure():
    client, _, _ = make_client(FakeOpener(TimeoutError("timed out")), max_retries=0)
    with pytest.raises(NetworkError):
        client.get_json(URL)


def test_recovers_after_a_transient_failure():
    opener = FakeOpener(urllib.error.URLError("down"), http_error(503), {"ok": True})
    client, calls, sleeps = make_client(opener)
    assert client.get_json(URL) == {"ok": True}
    assert len(calls) == 3
    assert sleeps == [1, 2]


def test_server_errors_end_as_provider_error():
    client, calls, _ = make_client(FakeOpener(http_error(500), http_error(500)), max_retries=1)
    with pytest.raises(ProviderError, match="HTTP 500") as error:
        client.get_json(URL)
    assert not isinstance(error.value, NetworkError)
    assert len(calls) == 2


def test_429_is_never_retried():
    opener = FakeOpener(http_error(429, {"Retry-After": "120"}), {"unused": True})
    client, calls, sleeps = make_client(opener)
    with pytest.raises(RateLimited) as error:
        client.get_json(URL)
    assert error.value.retry_after == 120
    assert len(calls) == 1
    assert sleeps == []
    assert len(opener.responses) == 1


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_client_errors_are_not_retried(code):
    client, calls, sleeps = make_client(FakeOpener(http_error(code)))
    with pytest.raises(ProviderError, match=f"HTTP {code}"):
        client.get_json(URL)
    assert len(calls) == 1
    assert sleeps == []


def test_redirects_are_refused():
    client, calls, _ = make_client(FakeOpener(http_error(302, {"Location": "https://evil.test"})))
    with pytest.raises(ProviderError, match="HTTP 302"):
        client.get_json(URL)
    assert len(calls) == 1


def test_plain_http_is_refused_without_any_request():
    client, calls, _ = make_client(FakeOpener())
    with pytest.raises(ProviderError, match="https"):
        client.get_json("http://example.test/")
    assert calls == []


@pytest.mark.parametrize("body", [b"<html>captive portal</html>", b'{"price": NaN}', b""])
def test_invalid_json_is_rejected(body):
    client, _, _ = make_client(FakeOpener(body))
    with pytest.raises(ProviderError, match="JSON"):
        client.get_json(URL)


def test_oversized_response_is_rejected():
    client, _, _ = make_client(FakeOpener(b"x" * (MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(ProviderError, match="grande"):
        client.get_json(URL)


def test_network_error_message_never_contains_a_key():
    failure = urllib.error.URLError(f"failed https://example.test/?api_token={SECRET}")
    client, _, _ = make_client(FakeOpener(failure), max_retries=0)
    with pytest.raises(NetworkError) as error:
        client.get_json(URL)
    assert SECRET not in str(error.value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("300", 300),
        (" 300 ", 300),
        (None, DEFAULT_COOLDOWN_SECONDS),
        ("", DEFAULT_COOLDOWN_SECONDS),
        ("soon", DEFAULT_COOLDOWN_SECONDS),
        ("5", MIN_COOLDOWN_SECONDS),
        ("-10", MIN_COOLDOWN_SECONDS),
        ("999999999", MAX_COOLDOWN_SECONDS),
    ],
)
def test_parse_retry_after(value, expected):
    assert parse_retry_after(value, now=1000.0) == expected


def test_parse_retry_after_accepts_an_http_date():
    now = 1_800_000_000.0
    assert parse_retry_after(formatdate(now + 900, usegmt=True), now) == 900
