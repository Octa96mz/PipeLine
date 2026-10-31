# PipeLine

Read-only market prices and sparklines for the Omarchy top bar.

**Status: early development.** The bar widget and data providers are not implemented yet, and
installation instructions will be added once they are.

This project is not financial advice and is not affiliated with any data provider.

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

## License

MIT
