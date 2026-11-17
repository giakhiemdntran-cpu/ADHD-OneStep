"""Daily Coaching Plan actions, isolated from existing OneStep task tables.

Stores user-scoped suggestion actions in a dedicated SQLite database. Can be
integrated with a real task service through an optional on_action callback.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

VALID_ACTIONS = {"start", "snooze", "done", "skip"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ActionResult:
    user_id: str
    suggestion_id: str
    action: str
    status: str
    created_at: str
    snooze_until: Optional[str] = None


class CoachingActionStore:
    def __init__(self, db_path: str | Path = "data/daily_coaching_actions.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _init_schema(self):
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS coaching_suggestion_state (
                user_id TEXT NOT NULL,
                suggestion_id TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                snooze_until TEXT,
                PRIMARY KEY (user_id, suggestion_id)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS coaching_suggestion_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                suggestion_id TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                snooze_until TEXT
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_coaching_events_user_time ON coaching_suggestion_events(user_id, created_at)")

    def perform(self, user_id: str, suggestion_id: str, action: str, *, snooze_minutes: int = 10) -> ActionResult:
        user_id, suggestion_id = str(user_id).strip(), str(suggestion_id).strip()
        if not user_id or not suggestion_id:
            raise ValueError("user_id and suggestion_id must be non-empty")
        if action not in VALID_ACTIONS:
            raise ValueError("Unknown action")
        if action == "snooze" and not 1 <= snooze_minutes <= 1440:
            raise ValueError("snooze_minutes must be 1..1440")
        moment = now_utc()
        created_at = iso(moment)
        snooze_until = iso(moment + timedelta(minutes=snooze_minutes)) if action == "snooze" else None
        status = {"start": "in_progress", "snooze": "snoozed", "done": "done", "skip": "skipped"}[action]
        with self._connect() as db:
            db.execute("""INSERT INTO coaching_suggestion_state(user_id,suggestion_id,status,updated_at,snooze_until)
                 VALUES(?,?,?,?,?) ON CONFLICT(user_id,suggestion_id) DO UPDATE SET
                 status=excluded.status, updated_at=excluded.updated_at,
                 snooze_until=excluded.snooze_until""",
                (user_id, suggestion_id, status, created_at, snooze_until))
            db.execute("""INSERT INTO coaching_suggestion_events
                 (user_id,suggestion_id,action,status,created_at,snooze_until)
                 VALUES(?,?,?,?,?,?)""", (user_id, suggestion_id, action, status, created_at, snooze_until))
        return ActionResult(user_id, suggestion_id, action, status, created_at, snooze_until)

    def state(self, user_id: str, suggestion_id: str) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT * FROM coaching_suggestion_state WHERE user_id=? AND suggestion_id=?",
                             (user_id, suggestion_id)).fetchone()
        if not row:
            return {"status": "pending", "snooze_until": None}
        state = dict(row)
        if state["status"] == "snoozed" and state["snooze_until"]:
            if datetime.fromisoformat(state["snooze_until"]) <= now_utc():
                return {**state, "status": "pending", "snooze_until": None, "reminder_due": True}
        return state

    def history(self, user_id: str, limit: int = 50) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("""SELECT * FROM coaching_suggestion_events
                WHERE user_id=? ORDER BY id DESC LIMIT ?""", (user_id, min(max(limit, 1), 500))).fetchall()
        return [dict(r) for r in rows]

    def reset_user(self, user_id: str) -> None:
        """Reset only the demo suggestion state/history for this profile."""
        with self._connect() as db:
            db.execute("DELETE FROM coaching_suggestion_state WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM coaching_suggestion_events WHERE user_id=?", (user_id,))
