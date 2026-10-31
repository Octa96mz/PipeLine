# PipeLine

Read-only market prices and sparklines for the Omarchy top bar.

**Status: early development.** Crypto prices can be fetched and inspected from the command line.
Indices and stocks have no data provider yet and are reported as `unavailable`. The bar element
exists but its panel is a placeholder, and installation instructions will be added once it is
finished.

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

## Bar element

`plugin/` is an Omarchy shell plugin (`pipeline.market`) that shows one to three prices from
`display.bar_items`, coloured by their variation. Stale data is shown dimmed, never green or red, and
a held price is marked with `!`. It only runs `pipeline json`, asynchronously and with a 3-second
timeout, and it never contacts a data provider.

By default it runs `~/.local/bin/pipeline`, a launcher created by `scripts/install-launcher.sh`. A
`command` setting on its entry in `shell.json` overrides that, and `refreshSeconds` (default 60,
minimum 15) sets how often it reads.

After installing or updating the plugin, restart the shell so it loads the new code:

```sh
omarchy restart shell
```

`omarchy-shell shell rescanPlugins` finds the plugin but was not enough to load changed code.

Tested with Omarchy 4.0.6, Hyprland 0.57.0 and Quickshell 0.3.2.

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
- The plugin uses `qs.Ui` and `KeyboardPanel` from the Omarchy shell. They load correctly from
  `~/.config` on the tested versions, but are not documented as a stable API for third parties, so an
  Omarchy update could break the plugin. The shell logs `Module path ... is outside of the config
  folder` for it; on the tested versions this had no visible effect.
- QML is linted with `qmllint`, which cannot resolve the shell's `qs.*` modules outside the shell, so
  it checks syntax but not those types. The widget's logic in `plugin/Model.js` is tested with Node.
- The green and red of the bar element are fixed colours, because the Omarchy theme does not define a
  green. They have not been checked against every theme.
- Sparkline timestamps are approximate: the API returns seven days of prices with no times.

## Planned for continuous integration

- CI must install Node.js and fail if the `plugin/Model.js` tests are skipped. They are skipped
  locally when Node.js is missing, which would otherwise hide a failure in CI.

## License

MIT
