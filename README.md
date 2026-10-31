# PipeLine

Read-only market prices and sparklines for the Omarchy top bar.

**Status: early development.** Crypto prices can be fetched and inspected from the command line.
Indices, stocks and the bar widget are not implemented yet, and installation instructions will be
added once they are.

This project is not financial advice and is not affiliated with any data provider.

## Data sources

Crypto prices (BTC, ETH, XRP, NEAR): Powered by CoinGecko, through its public keyless API.

- A failed or rate-limited refresh keeps the previous data and marks it as stale.
- On HTTP 429 the collector honours `Retry-After` (10 minutes if absent) and makes no further calls
  until then. On a shared VPN address this can happen without any fault on your side.
- Data not refreshed for 24 hours stops being shown and is deleted, as CoinGecko's terms require.
- CoinGecko publishes no numeric limit for keyless use, so `pipeline status` reports the calls made,
  not the calls remaining.

## Usage

```sh
pipeline fetch --dry-run   # show what would be called, without calling
pipeline fetch             # asks first; --yes skips the question
pipeline status
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
- Only Python 3.14 is tested, which is why `requires-python` is `>=3.14`.
- CoinGecko's documentation for `/coins/markets` shows only its paid host. The public host used here
  answered correctly during development, but could change.
- A real HTTP 429 from CoinGecko has not been observed. Handling it, including `Retry-After`, is
  tested only with synthetic responses.
- Sparkline timestamps are approximate: the API returns seven days of prices with no times.

## License

MIT
