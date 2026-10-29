"""Local profile database (README: main module 5) — stdlib SQLite.

Stores per-session hardware metadata, goal, settings before/after, per-trial
results, and the raw frame-time samples. Everything stays local; there is no
network code in this tool.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from optimize.models import OptimizationReport

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    game_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    bottleneck TEXT,
    hardware_json TEXT NOT NULL,
    baseline_settings TEXT NOT NULL,
    best_settings TEXT,
    baseline_score REAL,
    best_score REAL,
    recommendation TEXT,
    applied INTEGER NOT NULL DEFAULT 0,
    backup_id TEXT,
    notes TEXT,
    trials_json TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    label TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    frame_times_json TEXT NOT NULL,
    ts TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class SessionSummary:
    session_id: int
    ts: str
    game_id: str
    goal: str
    recommendation: str
    applied: bool
    baseline_avg_fps: float | None
    best_avg_fps: float | None


class ProfileDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(_SCHEMA)
        # Databases created before per-trial results were stored need the column.
        columns = [row[1] for row in self._conn.execute("PRAGMA table_info(sessions)")]
        if "trials_json" not in columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN trials_json TEXT")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save_session(self, report: OptimizationReport) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        trials = [
            {
                "label": t.candidate.label,
                "verdict": t.verdict,
                "reason": t.reason,
                "gain_pct": round(t.gain_pct, 2),
                "score": round(t.score, 4),
                "quality": round(t.quality, 3),
                "avg_fps": round(t.metrics.avg_fps, 2),
                "changes": t.candidate.changes,
            }
            for t in report.trials
        ]
        cur = self._conn.execute(
            """
            INSERT INTO sessions
                (ts, game_id, goal, bottleneck, hardware_json, baseline_settings,
                 best_settings, baseline_score, best_score, recommendation,
                 applied, backup_id, notes, trials_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                report.game_id,
                report.goal.value,
                report.bottleneck,
                json.dumps(report.hardware.to_dict()),
                json.dumps(report.baseline_settings, sort_keys=True),
                json.dumps(report.best_settings, sort_keys=True)
                if report.best_settings
                else None,
                report.baseline_score,
                report.best_score or None,
                report.recommendation,
                int(report.applied),
                report.backup_id,
                json.dumps(report.notes),
                json.dumps(trials),
            ),
        )
        session_id = int(cur.lastrowid)

        for run in report.raw_runs:
            self._conn.execute(
                """
                INSERT INTO runs
                    (session_id, label, settings_json, metrics_json, frame_times_json, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    run.label,
                    json.dumps(run.settings, sort_keys=True),
                    json.dumps(run.metrics.to_dict()),
                    json.dumps(list(run.frame_times_ms)),
                    now,
                ),
            )
        self._conn.commit()
        return session_id

    _SESSION_COLUMNS = (
        "id, ts, game_id, goal, bottleneck, hardware_json, baseline_settings, "
        "best_settings, baseline_score, best_score, recommendation, applied, "
        "backup_id, notes, trials_json"
    )

    def get_session(self, session_id: int) -> dict | None:
        row = self._conn.execute(
            f"SELECT {self._SESSION_COLUMNS} FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        keys = [c.strip() for c in self._SESSION_COLUMNS.split(",")]
        session = dict(zip(keys, row, strict=True))
        session["hardware"] = json.loads(session.pop("hardware_json"))
        session["baseline_settings"] = json.loads(session.pop("baseline_settings"))
        session["best_settings"] = (
            json.loads(session["best_settings"]) if session["best_settings"] else None
        )
        session["notes"] = json.loads(session["notes"] or "[]")
        session["trials"] = json.loads(session.pop("trials_json") or "[]")
        session["applied"] = bool(session["applied"])
        return session

    def session_runs(self, session_id: int) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT label, settings_json, metrics_json, frame_times_json
            FROM runs WHERE session_id = ? ORDER BY id
            """,
            (session_id,),
        ).fetchall()
        return [
            {
                "label": label,
                "settings": json.loads(settings_json),
                "metrics": json.loads(metrics_json),
                "frame_times_ms": json.loads(frames_json),
            }
            for label, settings_json, metrics_json, frames_json in rows
        ]

    def recent_sessions(self, limit: int = 20) -> list[SessionSummary]:
        rows = self._conn.execute(
            """
            SELECT id, ts, game_id, goal, recommendation, applied,
                   baseline_score, best_score
            FROM sessions ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        summaries = []
        for row in rows:
            session_id = row[0]
            base = self._conn.execute(
                "SELECT AVG(CAST(json_extract(metrics_json,'$.avg_fps') AS REAL)) "
                "FROM runs WHERE session_id = ? AND label = 'baseline'",
                (session_id,),
            ).fetchone()[0]
            best = self._conn.execute(
                "SELECT MAX(CAST(json_extract(metrics_json,'$.avg_fps') AS REAL)) "
                "FROM runs WHERE session_id = ? AND label != 'baseline'",
                (session_id,),
            ).fetchone()[0]
            summaries.append(
                SessionSummary(
                    session_id=session_id,
                    ts=row[1],
                    game_id=row[2],
                    goal=row[3],
                    recommendation=row[4],
                    applied=bool(row[5]),
                    baseline_avg_fps=round(base, 1) if base is not None else None,
                    best_avg_fps=round(best, 1) if best is not None else None,
                )
            )
        return summaries
