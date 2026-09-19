"""
SQLite persistence layer for Zalo SQL Exporter.

Design:
  - WAL mode for crash safety.
  - Raw observations are never deleted, only flagged.
  - Checkpoint stored in same transaction as observations.
  - Commit granularity: per viewport batch.
"""

import sqlite3
import uuid
import json
from datetime import datetime, timezone

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    config_json     TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    discover_method TEXT,
    last_update     TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    conv_local_id           TEXT PRIMARY KEY,
    run_id                  TEXT NOT NULL,
    display_name            TEXT NOT NULL,
    display_name_normalized TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pending',
    message_count           INTEGER NOT NULL DEFAULT 0,
    scroll_count            INTEGER NOT NULL DEFAULT 0,
    stop_reason             TEXT,
    earliest_date           TEXT,
    latest_date             TEXT,
    last_update             TEXT,
    error_msg               TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS observations (
    obs_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_local_id       TEXT NOT NULL,
    batch_number        INTEGER NOT NULL,
    position_in_batch   INTEGER NOT NULL,
    text_content        TEXT NOT NULL,
    sender              TEXT,
    element_type        TEXT,
    rect_top            INTEGER,
    rect_left           INTEGER,
    is_duplicate        INTEGER NOT NULL DEFAULT 0,
    possible_gap        INTEGER NOT NULL DEFAULT 0,
    captured_at         TEXT NOT NULL,
    FOREIGN KEY (conv_local_id) REFERENCES conversations(conv_local_id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    conv_local_id       TEXT PRIMARY KEY,
    last_batch_number   INTEGER NOT NULL,
    observation_count   INTEGER NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (conv_local_id) REFERENCES conversations(conv_local_id)
);

CREATE INDEX IF NOT EXISTS idx_obs_conv ON observations(conv_local_id);
CREATE INDEX IF NOT EXISTS idx_obs_batch ON observations(conv_local_id, batch_number);
CREATE INDEX IF NOT EXISTS idx_conv_run ON conversations(run_id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExporterDB:
    """Manages all database operations for the exporter."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or config.DB_FILE
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self):
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    # ----- Runs -----

    def create_run(self, conf: dict | None = None, discover_method: str = "scroll") -> str:
        run_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO runs (run_id, started_at, config_json, status, discover_method, last_update) "
            "VALUES (?, ?, ?, 'running', ?, ?)",
            (run_id, _now_iso(), json.dumps(conf) if conf else None, discover_method, _now_iso()),
        )
        self.conn.commit()
        return run_id

    def get_latest_run(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def update_run_status(self, run_id: str, status: str):
        self.conn.execute(
            "UPDATE runs SET status=?, last_update=? WHERE run_id=?",
            (status, _now_iso(), run_id),
        )
        self.conn.commit()

    # ----- Conversations -----

    def add_conversation(self, run_id: str, display_name: str,
                         display_name_normalized: str) -> str:
        conv_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO conversations "
            "(conv_local_id, run_id, display_name, display_name_normalized, "
            " status, last_update) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (conv_id, run_id, display_name, display_name_normalized, _now_iso()),
        )
        self.conn.commit()
        return conv_id

    def find_conversation_by_name(self, run_id: str, normalized_name: str) -> dict | None:
        """Find conversation by normalized name in a given run."""
        row = self.conn.execute(
            "SELECT * FROM conversations "
            "WHERE run_id=? AND display_name_normalized=?",
            (run_id, normalized_name),
        ).fetchone()
        return dict(row) if row else None

    def is_already_completed(self, normalized_name: str) -> bool:
        """Check if this contact was already completed in ANY previous run."""
        row = self.conn.execute(
            "SELECT 1 FROM conversations "
            "WHERE display_name_normalized=? AND status='completed' "
            "LIMIT 1",
            (normalized_name,),
        ).fetchone()
        return row is not None

    def get_conversations(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM conversations WHERE run_id=? ORDER BY display_name",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_pending_conversations(self, run_id: str) -> list[dict]:
        """Return conversations that still need extraction."""
        rows = self.conn.execute(
            "SELECT * FROM conversations WHERE run_id=? AND status IN ('pending', 'in_progress', 'partial') "
            "ORDER BY display_name",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_conversation_status(self, conv_id: str, status: str,
                                   stop_reason: str | None = None,
                                   error_msg: str | None = None):
        self.conn.execute(
            "UPDATE conversations SET status=?, stop_reason=?, error_msg=?, last_update=? "
            "WHERE conv_local_id=?",
            (status, stop_reason, error_msg, _now_iso(), conv_id),
        )
        self.conn.commit()

    def update_conversation_counts(self, conv_id: str, message_count: int,
                                   scroll_count: int):
        self.conn.execute(
            "UPDATE conversations SET message_count=?, scroll_count=?, last_update=? "
            "WHERE conv_local_id=?",
            (message_count, scroll_count, _now_iso(), conv_id),
        )
        self.conn.commit()

    def update_conversation_dates(self, conv_id: str, earliest: str | None,
                                  latest: str | None):
        self.conn.execute(
            "UPDATE conversations SET earliest_date=?, latest_date=?, last_update=? "
            "WHERE conv_local_id=?",
            (earliest, latest, _now_iso(), conv_id),
        )
        self.conn.commit()

    # ----- Observations -----

    def commit_batch(self, conv_id: str, batch_number: int,
                     items: list[dict]):
        """
        Atomically commit a batch of observations and update checkpoint.

        Each item dict has keys:
          text_content, sender, element_type, rect_top, rect_left,
          is_duplicate, possible_gap
        """
        now = _now_iso()
        with self.conn:
            for pos, item in enumerate(items):
                self.conn.execute(
                    "INSERT INTO observations "
                    "(conv_local_id, batch_number, position_in_batch, "
                    " text_content, sender, element_type, rect_top, rect_left, "
                    " is_duplicate, possible_gap, captured_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        conv_id, batch_number, pos,
                        item["text_content"], item.get("sender"),
                        item.get("element_type"), item.get("rect_top"),
                        item.get("rect_left"),
                        int(item.get("is_duplicate", False)),
                        int(item.get("possible_gap", False)),
                        now,
                    ),
                )
            # Get total observation count for this conversation
            count = self.conn.execute(
                "SELECT COUNT(*) FROM observations WHERE conv_local_id=?",
                (conv_id,),
            ).fetchone()[0]
            # Upsert checkpoint
            self.conn.execute(
                "INSERT INTO checkpoints (conv_local_id, last_batch_number, observation_count, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(conv_local_id) DO UPDATE SET "
                "last_batch_number=excluded.last_batch_number, "
                "observation_count=excluded.observation_count, "
                "updated_at=excluded.updated_at",
                (conv_id, batch_number, count, now),
            )
        # Update conversation message count outside the transaction
        self.update_conversation_counts(conv_id, count, batch_number)

    def get_checkpoint(self, conv_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM checkpoints WHERE conv_local_id=?",
            (conv_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_observations(self, conv_id: str, exclude_duplicates: bool = True) -> list[dict]:
        """Get observations for a conversation, optionally excluding flagged duplicates."""
        if exclude_duplicates:
            rows = self.conn.execute(
                "SELECT * FROM observations WHERE conv_local_id=? AND is_duplicate=0 "
                "ORDER BY batch_number, position_in_batch",
                (conv_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM observations WHERE conv_local_id=? "
                "ORDER BY batch_number, position_in_batch",
                (conv_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_observations(self, run_id: str, exclude_duplicates: bool = True) -> list[dict]:
        """Get all observations across conversations for a run."""
        dup_clause = "AND o.is_duplicate=0" if exclude_duplicates else ""
        rows = self.conn.execute(
            f"SELECT o.*, c.display_name FROM observations o "
            f"JOIN conversations c ON o.conv_local_id = c.conv_local_id "
            f"WHERE c.run_id=? {dup_clause} "
            f"ORDER BY c.display_name, o.batch_number, o.position_in_batch",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_observations_all_runs(self, exclude_duplicates: bool = True) -> list[dict]:
        """Get all observations across ALL runs (for complete export)."""
        dup_clause = "AND o.is_duplicate=0" if exclude_duplicates else ""
        rows = self.conn.execute(
            f"SELECT o.*, c.display_name FROM observations o "
            f"JOIN conversations c ON o.conv_local_id = c.conv_local_id "
            f"WHERE 1=1 {dup_clause} "
            f"ORDER BY c.display_name, o.batch_number, o.position_in_batch",
        ).fetchall()
        return [dict(r) for r in rows]

    # ----- Duplicate flagging -----

    def flag_duplicates_in_batch(self, conv_id: str, batch_number: int,
                                 duplicate_positions: list[int]):
        """Flag specific positions within a batch as duplicates."""
        if not duplicate_positions:
            return
        with self.conn:
            for pos in duplicate_positions:
                self.conn.execute(
                    "UPDATE observations SET is_duplicate=1 "
                    "WHERE conv_local_id=? AND batch_number=? AND position_in_batch=?",
                    (conv_id, batch_number, pos),
                )

    # ----- Status / summary -----

    def get_run_summary(self, run_id: str) -> dict:
        """Return a summary of the run for status display."""
        run = self.conn.execute(
            "SELECT * FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not run:
            return {}
        convs = self.get_conversations(run_id)
        total_obs = self.conn.execute(
            "SELECT COUNT(*) FROM observations o "
            "JOIN conversations c ON o.conv_local_id=c.conv_local_id "
            "WHERE c.run_id=? AND o.is_duplicate=0",
            (run_id,),
        ).fetchone()[0]
        return {
            "run": dict(run),
            "conversations": convs,
            "total_observations": total_obs,
        }
