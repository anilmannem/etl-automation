"""SQLite-backed test result store for historical trending."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pandas as pd

from ..checks.base import CheckResult

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS test_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    suite       TEXT NOT NULL,
    check_type  TEXT NOT NULL,
    source      TEXT,
    target      TEXT,
    status      TEXT NOT NULL,
    message     TEXT,
    metrics_json TEXT,
    details_json TEXT,
    duration_s  REAL
);

CREATE INDEX IF NOT EXISTS idx_results_suite ON test_results(suite);
CREATE INDEX IF NOT EXISTS idx_results_ts    ON test_results(timestamp);
"""


class ResultStore:
    """Persists check results to SQLite for historical analysis."""

    def __init__(self, db_path: str | Path = "etl_validator_results.db"):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.executescript(_SCHEMA)
        self._migrate_schema()
        self._conn.commit()
        logger.info("Result store initialised at %s", self.db_path)

    def _migrate_schema(self):
        """Add missing columns if upgrading from an older schema."""
        cursor = self._conn.execute("PRAGMA table_info(test_results)")
        columns = {row[1] for row in cursor.fetchall()}
        if "details_json" not in columns:
            self._conn.execute(
                "ALTER TABLE test_results ADD COLUMN details_json TEXT"
            )
            logger.info("Migrated result store: added details_json column")
        if "batch_id" not in columns:
            self._conn.execute(
                "ALTER TABLE test_results ADD COLUMN batch_id TEXT"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_results_batch ON test_results(batch_id)"
            )
            logger.info("Migrated result store: added batch_id column")

    def record(self, run_id: str, suite: str, result: CheckResult,
               source: str = "", target: str = "", duration_s: float = 0.0,
               batch_id: str = ""):
        """Write a single check result."""
        # Serialize top 100 detail rows
        details_json = None
        if result.details is not None and len(result.details) > 0:
            details_json = result.details.head(100).to_json(orient="records")

        self._conn.execute(
            """INSERT INTO test_results
               (run_id, suite, check_type, source, target, status, message, metrics_json, details_json, duration_s, batch_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, suite, result.check_type,
                source, target, str(result.status),
                result.message, json.dumps(result.metrics),
                details_json,
                duration_s,
                batch_id or None,
            ),
        )
        self._conn.commit()

    def record_suite(self, suite_result, batch_id: str = "",
                     source: str = "", target: str = ""):
        """Record all results from a SuiteResult."""
        for r in suite_result.results:
            self.record(
                run_id=suite_result.run_id,
                suite=suite_result.suite_name,
                result=r,
                source=source,
                target=target,
                duration_s=suite_result.duration_seconds / max(len(suite_result.results), 1),
                batch_id=batch_id,
            )

    def get_history(self, suite: str | None = None, days: int = 30) -> pd.DataFrame:
        """Get historical results as a DataFrame."""
        query = """
            SELECT run_id, timestamp, suite, check_type, source, target,
                   status, message, metrics_json, batch_id, duration_s
            FROM test_results
            WHERE timestamp > datetime('now', ?)
        """
        params: list = [f"-{days} days"]
        if suite:
            query += " AND suite = ?"
            params.append(suite)
        query += " ORDER BY timestamp DESC"
        return pd.read_sql_query(query, self._conn, params=params)

    def get_batch(self, batch_id: str) -> list[dict] | None:
        """Fetch all check rows for a batch, grouped by run_id."""
        cursor = self._conn.execute(
            """SELECT run_id, timestamp, suite, check_type, source, target,
                      status, message, metrics_json, details_json, duration_s, batch_id
               FROM test_results WHERE batch_id = ?
               ORDER BY id""",
            (batch_id,),
        )
        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
        return rows if rows else None

    def get_run(self, run_id: str) -> list[dict] | None:
        """Fetch all check rows for a single run, including details."""
        cursor = self._conn.execute(
            """SELECT run_id, timestamp, suite, check_type, source, target,
                      status, message, metrics_json, details_json, duration_s
               FROM test_results WHERE run_id = ?
               ORDER BY id""",
            (run_id,),
        )
        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
        return rows if rows else None

    def close(self):
        self._conn.close()
