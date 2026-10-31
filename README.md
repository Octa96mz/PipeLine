# PipeLine

Read-only market prices and sparklines for the Omarchy top bar.

**Status: early development.** Crypto prices can be fetched and inspected from the command line.
Indices and stocks have no data provider yet and are reported as `unavailable`. The bar widget is
not implemented yet, and installation instructions will be added once it is.

This project is not financial advice and is not affiliated with any data provider.

## Data sources

Crypto prices (BTC, ETH, XRP, NEAR): Powered by CoinGecko, through its public keyless API.

- A failed or rate-limited refresh keeps the previous data and marks it as stale.
- On HTTP 429 the collector honours `Retry-After` (10 minutes if absent) and makes no further calls
  until then. On a shared VPN address this can happen without any fault on your side.
- Data not refreshed for 24 hours stops being shown and is deleted, as CoinGecko's terms require.
- CoinGecko publishes no numeric limit for keyless use, so `pipeline status` reports the calls made,
  not the calls remaining. Only requests that could have reached the server are counted: DNS and
  connection failures, including a VPN kill switch, are not.
- After repeated network failures, scheduled runs space out: the interval doubles from the second
  failure in a row, up to `max_offline_interval_minutes` (default 20), and returns to normal after the first run that reaches the
  provider. A manual fetch is not delayed.

### Held prices

A new price more than `max_jump_percent` (default 50 %) away from the last valid one is not applied.
The symbol is shown as `held` ("retenido") with the rejected price and the size of the jump, in
`pipeline status`, `pipeline show` and `pipeline json`, and it keeps showing the last valid price.

This also happens with a genuine move. The hold ends when a price within the limit arrives, or once
the last valid price is more than 24 hours old, when the new price is accepted. Raise
`max_jump_percent` to hold less often.

## Usage

```sh
pipeline fetch --dry-run   # show what would be called, without calling
pipeline fetch             # asks first; --yes skips the question
pipeline status
pipeline show              # prices and sparklines in the terminal
pipeline json              # data for the bar; see docs/json-schema.md
```

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install -e .
.venv/bin/pytest
.venv/bin/ruff check .
```

## Not yet validated

- Development dependencies are pinned to exact versions, but `requirements-dev.lock` has no hashes,
  so downloaded packages are not verified against known digests.
- The Python requirement is tested only with Python 3.14, which is why `requires-python` is
  `>=3.14`.
- CoinGecko's documentation for `/coins/markets` shows only its paid host. The public host used here
  answered correctly during development, but could change.
- HTTP 429 handling, including `Retry-After`, is tested only with simulated responses. A real 429
  from CoinGecko has not been observed.
- Request counting relies on how Python's `urllib` reports failures. It was tested without network
  access, by simulating failures at the connection and response stages.
- Sparkline timestamps are approximate: the API returns seven days of prices with no times.

## License

MIT
