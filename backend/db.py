"""Small SQLite wrapper. The database is deliberately boring and local-first."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any


def data_dir() -> Path:
    configured = os.getenv("AUTOMATA_DATA_DIR")
    root = Path(configured) if configured else Path(__file__).resolve().parent.parent / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "automata.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS macros (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    modified_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    macro_id TEXT,
                    status TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    FOREIGN KEY(macro_id) REFERENCES macros(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id, id);
                """
            )

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock, self._connection:
            return self._connection.execute(sql, parameters)

    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        with self._lock, self._connection:
            self._connection.executemany(sql, rows)

    def one(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(sql, parameters).fetchone()

    def all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(sql, parameters).fetchall()


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def decode(value: str) -> Any:
    return json.loads(value)

