"""Persistence services used by the API and execution manager."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .db import Database, decode, encode
from .schemas import Macro, utc_now


class Storage:
    def __init__(self, database: Database) -> None:
        self.db = database

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.db.one("SELECT value FROM settings WHERE key = ?", (key,))
        return default if row is None else decode(row["value"])

    def set_setting(self, key: str, value: Any) -> None:
        self.db.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, encode(value), utc_now()),
        )

    def save_macro(self, macro: Macro) -> Macro:
        now = utc_now()
        macro_id = macro.id or str(uuid.uuid4())
        created_at = macro.created_at or now
        saved = macro.model_copy(update={"id": macro_id, "created_at": created_at, "modified_at": now})
        self.db.execute(
            """
            INSERT INTO macros(id, name, data, created_at, modified_at) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name, data=excluded.data, modified_at=excluded.modified_at
            """,
            (macro_id, saved.name, encode(saved.model_dump(mode="json")), created_at, now),
        )
        return saved

    def get_macro(self, macro_id: str) -> Macro | None:
        row = self.db.one("SELECT data FROM macros WHERE id = ?", (macro_id,))
        return None if row is None else Macro.model_validate(decode(row["data"]))

    def list_macros(self, query: str = "") -> list[Macro]:
        if query:
            rows = self.db.all(
                "SELECT data FROM macros WHERE name LIKE ? OR data LIKE ? ORDER BY modified_at DESC",
                (f"%{query}%", f"%{query}%"),
            )
        else:
            rows = self.db.all("SELECT data FROM macros ORDER BY modified_at DESC")
        return [Macro.model_validate(decode(row["data"])) for row in rows]

    def delete_macro(self, macro_id: str) -> bool:
        cursor = self.db.execute("DELETE FROM macros WHERE id = ?", (macro_id,))
        return cursor.rowcount > 0

    def create_run(self, run_id: str, macro_id: str | None, data: dict[str, Any], status: str = "Draft") -> dict[str, Any]:
        created_at = utc_now()
        record = {**data, "id": run_id, "macro_id": macro_id, "status": status, "created_at": created_at}
        self.db.execute(
            "INSERT INTO runs(id, macro_id, status, data, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, macro_id, status, encode(record), created_at),
        )
        return record

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT data FROM runs WHERE id = ?", (run_id,))
        return None if row is None else decode(row["data"])

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT data FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [decode(row["data"]) for row in rows]

    def update_run(self, run_id: str, **updates: Any) -> dict[str, Any] | None:
        current = self.get_run(run_id)
        if current is None:
            return None
        current.update(updates)
        status = current.get("status", "Draft")
        started_at = current.get("started_at")
        finished_at = current.get("finished_at")
        self.db.execute(
            "UPDATE runs SET status = ?, data = ?, started_at = ?, finished_at = ? WHERE id = ?",
            (status, encode(current), started_at, finished_at, run_id),
        )
        return current

    def append_event(self, run_id: str, event_type: str, data: dict[str, Any]) -> int:
        cursor = self.db.execute(
            "INSERT INTO run_events(run_id, created_at, event_type, data) VALUES (?, ?, ?, ?)",
            (run_id, utc_now(), event_type, encode(data)),
        )
        return int(cursor.lastrowid)

    def list_events(self, run_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT id, created_at, event_type, data FROM run_events WHERE run_id = ? AND id > ? ORDER BY id",
            (run_id, after_id),
        )
        return [
            {"id": row["id"], "created_at": row["created_at"], "type": row["event_type"], **decode(row["data"])}
            for row in rows
        ]

    def recover_interrupted_runs(self) -> None:
        rows = self.db.all("SELECT id, data FROM runs WHERE status IN ('Planning', 'Running', 'Paused')")
        for row in rows:
            record = decode(row["data"])
            record.update(
                {
                    "status": "Failed",
                    "error": {
                        "kind": "interrupted",
                        "message": "The application restarted while this run was active.",
                        "recovery": "Review the last completed step and start the macro again when ready.",
                    },
                    "finished_at": utc_now(),
                }
            )
            self.db.execute(
                "UPDATE runs SET status = 'Failed', data = ?, finished_at = ? WHERE id = ?",
                (encode(record), record["finished_at"], row["id"]),
            )

