import os
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pipeline.errors import DatabaseError
from pipeline.redact import redact_text

ASSET_CLASSES = ("crypto", "index", "stock")
PRICE_KINDS = ("live", "close")
OUTCOMES = ("ok", "partial", "error")

# Se ejecutan en orden. Una base de datos existente aplica solo las que le faltan.
_MIGRATIONS = (
    """
    CREATE TABLE quotes (
        symbol         TEXT PRIMARY KEY,
        asset_class    TEXT NOT NULL CHECK (asset_class IN ('crypto', 'index', 'stock')),
        provider       TEXT NOT NULL,
        price          REAL NOT NULL CHECK (price > 0),
        currency       TEXT,
        change_percent REAL,
        kind           TEXT NOT NULL CHECK (kind IN ('live', 'close')),
        price_time     INTEGER NOT NULL,
        fetched_at     INTEGER NOT NULL
    ) STRICT;

    CREATE TABLE series_points (
        symbol TEXT NOT NULL REFERENCES quotes(symbol) ON DELETE CASCADE,
        ts     INTEGER NOT NULL,
        value  REAL NOT NULL CHECK (value > 0),
        PRIMARY KEY (symbol, ts)
    ) STRICT, WITHOUT ROWID;

    CREATE TABLE api_calls (
        id        INTEGER PRIMARY KEY,
        provider  TEXT NOT NULL,
        called_at INTEGER NOT NULL
    ) STRICT;
    CREATE INDEX api_calls_provider_time ON api_calls (provider, called_at);

    CREATE TABLE fetch_attempts (
        id          INTEGER PRIMARY KEY,
        provider    TEXT NOT NULL,
        finished_at INTEGER NOT NULL,
        outcome     TEXT NOT NULL CHECK (outcome IN ('ok', 'partial', 'error')),
        detail      TEXT
    ) STRICT;
    CREATE INDEX fetch_attempts_provider_time ON fetch_attempts (provider, finished_at);
    """,
)


@dataclass(frozen=True)
class Quote:
    symbol: str
    asset_class: str
    provider: str
    price: float
    # None en los índices: se expresan en puntos, no en una moneda.
    currency: str | None
    change_percent: float | None
    kind: str
    price_time: int
    fetched_at: int


@dataclass(frozen=True)
class FetchAttempt:
    provider: str
    finished_at: int
    outcome: str
    detail: str | None


class Database:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, path: Path) -> Self:
        """Abre para escritura, creando el fichero con permisos 600 y aplicando migraciones."""
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.close(os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600))
            connection = sqlite3.connect(path, timeout=5, autocommit=True)
        except (OSError, sqlite3.Error) as error:
            raise DatabaseError(f"{path}: no se pudo abrir: {error}") from error
        database = cls(connection)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA foreign_keys = ON")
            database._migrate()
        except (sqlite3.Error, DatabaseError) as error:
            connection.close()
            raise DatabaseError(f"{path}: no se pudo inicializar: {error}") from error
        return database

    @classmethod
    def open_readonly(cls, path: Path) -> Self:
        """Abre para los lectores (`status`, `show`, `json`). No crea ni modifica nada."""
        try:
            connection = sqlite3.connect(
                f"{path.absolute().as_uri()}?mode=ro", timeout=1, uri=True, autocommit=True
            )
            database = cls(connection)
            if database.schema_version() > len(_MIGRATIONS):
                connection.close()
                raise DatabaseError(f"{path}: creada por una versión más reciente de PipeLine")
        except sqlite3.Error as error:
            raise DatabaseError(f"{path}: no se pudo abrir: {error}") from error
        return database

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def schema_version(self) -> int:
        return self._connection.execute("PRAGMA user_version").fetchone()[0]

    def _migrate(self) -> None:
        version = self.schema_version()
        if version > len(_MIGRATIONS):
            raise DatabaseError("creada por una versión más reciente de PipeLine")
        for number, script in enumerate(_MIGRATIONS[version:], start=version + 1):
            # executescript agrupa la migración y su versión en una sola transacción.
            try:
                self._connection.executescript(
                    f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;"
                )
            except sqlite3.Error:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        self._connection.execute("COMMIT")

    def save_snapshot(self, quote: Quote, series: Iterable[tuple[int, float]]) -> None:
        """Sustituye el último dato de un símbolo y su serie: se guardan ambos o ninguno."""
        with self._transaction():
            self._connection.execute(
                """
                INSERT INTO quotes (symbol, asset_class, provider, price, currency,
                                    change_percent, kind, price_time, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol) DO UPDATE SET
                    asset_class = excluded.asset_class,
                    provider = excluded.provider,
                    price = excluded.price,
                    currency = excluded.currency,
                    change_percent = excluded.change_percent,
                    kind = excluded.kind,
                    price_time = excluded.price_time,
                    fetched_at = excluded.fetched_at
                """,
                (
                    quote.symbol,
                    quote.asset_class,
                    quote.provider,
                    quote.price,
                    quote.currency,
                    quote.change_percent,
                    quote.kind,
                    quote.price_time,
                    quote.fetched_at,
                ),
            )
            self._connection.execute("DELETE FROM series_points WHERE symbol = ?", (quote.symbol,))
            self._connection.executemany(
                "INSERT INTO series_points (symbol, ts, value) VALUES (?, ?, ?)",
                [(quote.symbol, ts, value) for ts, value in series],
            )

    def quote(self, symbol: str) -> Quote | None:
        row = self._connection.execute(
            """
            SELECT symbol, asset_class, provider, price, currency, change_percent, kind,
                   price_time, fetched_at
            FROM quotes WHERE symbol = ?
            """,
            (symbol,),
        ).fetchone()
        return Quote(*row) if row else None

    def series(self, symbol: str) -> list[tuple[int, float]]:
        rows = self._connection.execute(
            "SELECT ts, value FROM series_points WHERE symbol = ? ORDER BY ts", (symbol,)
        )
        return [(ts, value) for ts, value in rows]

    def record_api_call(self, provider: str, called_at: int) -> None:
        """Anota una llamada antes de enviarla: las fallidas también pueden consumir cuota."""
        self._connection.execute(
            "INSERT INTO api_calls (provider, called_at) VALUES (?, ?)", (provider, called_at)
        )

    def calls_since(self, provider: str, since: int) -> int:
        return self._connection.execute(
            "SELECT COUNT(*) FROM api_calls WHERE provider = ? AND called_at >= ?",
            (provider, since),
        ).fetchone()[0]

    def remaining_calls(self, provider: str, budget: int, now: int) -> int:
        """Llamadas disponibles en las últimas 24 horas. Nunca devuelve un valor negativo."""
        return max(0, budget - self.calls_since(provider, now - 86_400))

    def record_attempt(
        self, provider: str, finished_at: int, outcome: str, detail: str | None = None
    ) -> None:
        # El detalle suele venir de una excepción, que puede contener la URL con la clave.
        safe_detail = redact_text(detail) if detail is not None else None
        self._connection.execute(
            "INSERT INTO fetch_attempts (provider, finished_at, outcome, detail) "
            "VALUES (?, ?, ?, ?)",
            (provider, finished_at, outcome, safe_detail),
        )

    def last_attempt(self, provider: str) -> FetchAttempt | None:
        row = self._connection.execute(
            """
            SELECT provider, finished_at, outcome, detail FROM fetch_attempts
            WHERE provider = ? ORDER BY finished_at DESC, id DESC LIMIT 1
            """,
            (provider,),
        ).fetchone()
        return FetchAttempt(*row) if row else None
