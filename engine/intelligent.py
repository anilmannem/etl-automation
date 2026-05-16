"""Intelligent validation engine — adaptive, incremental, lineage-aware.

Features:
- **Pyramid Validation**: Aggregate-first check, drill only on failure (skips 80% of heavy work)
- **Incremental Validation**: Watermark-based delta — only validates changed rows
- **Adaptive Strategy Selection**: Auto-selects optimal comparison strategy per table
- **Table Profiling**: Tracks table characteristics and strategy performance
- **Lineage-Aware Execution**: Skips downstream tables when upstream fails
- **Work-Stealing Job Queue**: Dynamic multi-worker load balancing
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TABLE PROFILE STORE — tracks table metadata, watermarks, strategy performance
# ═══════════════════════════════════════════════════════════════════════════════

_PROFILE_SCHEMA = """
CREATE TABLE IF NOT EXISTS table_profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name      TEXT NOT NULL,
    connection_dsn  TEXT NOT NULL DEFAULT '',
    row_count       INTEGER DEFAULT 0,
    last_row_count  INTEGER DEFAULT 0,
    change_rate_pct REAL DEFAULT 0.0,
    avg_row_size_bytes INTEGER DEFAULT 0,
    has_timestamp_col TEXT DEFAULT '',
    detected_keys   TEXT DEFAULT '',
    last_strategy   TEXT DEFAULT '',
    last_duration_s REAL DEFAULT 0.0,
    last_validated  TEXT DEFAULT '',
    last_watermark  TEXT DEFAULT '',
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(table_name, connection_dsn)
);

CREATE TABLE IF NOT EXISTS strategy_performance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name  TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    row_count   INTEGER DEFAULT 0,
    duration_s  REAL NOT NULL,
    success     INTEGER NOT NULL DEFAULT 1,
    timestamp   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_profile_table ON table_profiles(table_name);
CREATE INDEX IF NOT EXISTS idx_strategy_perf ON strategy_performance(table_name, strategy);

CREATE TABLE IF NOT EXISTS table_lineage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT NOT NULL,
    target_table TEXT NOT NULL,
    UNIQUE(source_table, target_table)
);

CREATE TABLE IF NOT EXISTS job_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    TEXT NOT NULL,
    table_pair  TEXT NOT NULL,
    suite_config TEXT NOT NULL,
    priority    REAL NOT NULL DEFAULT 50.0,
    status      TEXT NOT NULL DEFAULT 'pending',
    worker_id   TEXT,
    claimed_at  TEXT,
    completed_at TEXT,
    result_json TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON job_queue(status, priority DESC);
CREATE INDEX IF NOT EXISTS idx_queue_batch ON job_queue(batch_id);

CREATE TABLE IF NOT EXISTS validation_metadata (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name      TEXT NOT NULL DEFAULT 'default',
    source_connection TEXT NOT NULL,
    source_table    TEXT NOT NULL,
    target_connection TEXT NOT NULL,
    target_table    TEXT NOT NULL,
    join_keys       TEXT DEFAULT '',
    check_types     TEXT NOT NULL DEFAULT 'row_count,data',
    strategy        TEXT NOT NULL DEFAULT 'auto',
    priority        REAL NOT NULL DEFAULT 50.0,
    tolerance       REAL DEFAULT 0.0,
    where_clause    TEXT DEFAULT '',
    ignore_columns  TEXT DEFAULT 'DL_INSERT_TS,DL_UPDATE_TS',
    timestamp_column TEXT DEFAULT 'DL_UPDATE_TS',
    schedule        TEXT DEFAULT 'daily',
    active          INTEGER NOT NULL DEFAULT 1,
    tags            TEXT DEFAULT '',
    notes           TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_meta_group ON validation_metadata(group_name);
CREATE INDEX IF NOT EXISTS idx_meta_active ON validation_metadata(active);
CREATE INDEX IF NOT EXISTS idx_meta_priority ON validation_metadata(priority DESC);
"""


class IntelligentStore:
    """SQLite store for table profiles, strategy performance, lineage, and job queue."""

    def __init__(self, db_path: str | Path = "etl_validator_results.db"):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")  # concurrent readers
        self._conn.executescript(_PROFILE_SCHEMA)
        self._conn.commit()

    # ── Table Profile Operations ──────────────────────────────────────────────

    def get_profile(self, table_name: str, dsn: str = "") -> dict | None:
        cursor = self._conn.execute(
            "SELECT * FROM table_profiles WHERE table_name = ? AND connection_dsn = ?",
            (table_name.upper(), dsn),
        )
        cols = [d[0] for d in cursor.description]
        row = cursor.fetchone()
        return dict(zip(cols, row)) if row else None

    def update_profile(self, table_name: str, dsn: str = "", **kwargs):
        """Upsert a table profile with the given fields."""
        table_name = table_name.upper()
        existing = self.get_profile(table_name, dsn)
        if existing:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            values = list(kwargs.values()) + [table_name, dsn]
            self._conn.execute(
                f"UPDATE table_profiles SET {sets}, updated_at = datetime('now') "
                f"WHERE table_name = ? AND connection_dsn = ?",
                values,
            )
        else:
            kwargs["table_name"] = table_name
            kwargs["connection_dsn"] = dsn
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" * len(kwargs))
            self._conn.execute(
                f"INSERT INTO table_profiles ({cols}) VALUES ({placeholders})",
                list(kwargs.values()),
            )
        self._conn.commit()

    def get_watermark(self, table_name: str, dsn: str = "") -> str | None:
        """Get the last validated watermark (timestamp) for a table."""
        profile = self.get_profile(table_name, dsn)
        return profile["last_watermark"] if profile and profile["last_watermark"] else None

    def set_watermark(self, table_name: str, watermark: str, dsn: str = ""):
        """Update the watermark after successful validation."""
        self.update_profile(table_name, dsn,
                            last_watermark=watermark,
                            last_validated=watermark)

    # ── Strategy Performance Tracking ────────────────────────────────────────

    def record_strategy_performance(self, table_name: str, strategy: str,
                                    row_count: int, duration_s: float, success: bool = True):
        """Record how a strategy performed on a table (for adaptive selection)."""
        self._conn.execute(
            "INSERT INTO strategy_performance (table_name, strategy, row_count, duration_s, success) "
            "VALUES (?, ?, ?, ?, ?)",
            (table_name.upper(), strategy, row_count, duration_s, int(success)),
        )
        self._conn.commit()

    def get_best_strategy(self, table_name: str) -> str | None:
        """Get the fastest successful strategy for this table (based on history)."""
        cursor = self._conn.execute(
            """SELECT strategy, AVG(duration_s) as avg_duration
               FROM strategy_performance
               WHERE table_name = ? AND success = 1
               GROUP BY strategy
               ORDER BY avg_duration ASC
               LIMIT 1""",
            (table_name.upper(),),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    # ── Lineage Operations ────────────────────────────────────────────────────

    def set_lineage(self, source_table: str, target_table: str):
        """Define a lineage relationship: source_table feeds target_table."""
        self._conn.execute(
            "INSERT OR IGNORE INTO table_lineage (source_table, target_table) VALUES (?, ?)",
            (source_table.upper(), target_table.upper()),
        )
        self._conn.commit()

    def get_downstream(self, table_name: str) -> list[str]:
        """Get all tables that depend on this table (directly or transitively)."""
        downstream = set()
        queue = [table_name.upper()]
        while queue:
            current = queue.pop(0)
            cursor = self._conn.execute(
                "SELECT target_table FROM table_lineage WHERE source_table = ?",
                (current,),
            )
            for row in cursor.fetchall():
                if row[0] not in downstream:
                    downstream.add(row[0])
                    queue.append(row[0])
        return list(downstream)

    def get_upstream(self, table_name: str) -> list[str]:
        """Get all tables that this table depends on."""
        upstream = set()
        queue = [table_name.upper()]
        while queue:
            current = queue.pop(0)
            cursor = self._conn.execute(
                "SELECT source_table FROM table_lineage WHERE target_table = ?",
                (current,),
            )
            for row in cursor.fetchall():
                if row[0] not in upstream:
                    upstream.add(row[0])
                    queue.append(row[0])
        return list(upstream)

    # ── Job Queue Operations (Work-Stealing) ─────────────────────────────────

    def enqueue_jobs(self, batch_id: str, jobs: list[dict]):
        """Add a batch of validation jobs to the queue.

        Each job dict: {table_pair, suite_config, priority}
        """
        for job in jobs:
            self._conn.execute(
                "INSERT INTO job_queue (batch_id, table_pair, suite_config, priority) "
                "VALUES (?, ?, ?, ?)",
                (batch_id, job["table_pair"], json.dumps(job["suite_config"]),
                 job.get("priority", 50.0)),
            )
        self._conn.commit()
        logger.info("Enqueued %d jobs for batch %s", len(jobs), batch_id)

    def claim_next_job(self, worker_id: str) -> dict | None:
        """Atomically claim the highest-priority pending job (work-stealing)."""
        # SQLite doesn't support UPDATE ... LIMIT with RETURNING, so two-step
        cursor = self._conn.execute(
            "SELECT id, batch_id, table_pair, suite_config, priority "
            "FROM job_queue WHERE status = 'pending' "
            "ORDER BY priority DESC LIMIT 1",
        )
        row = cursor.fetchone()
        if not row:
            return None

        job_id = row[0]
        # Attempt atomic claim
        self._conn.execute(
            "UPDATE job_queue SET status = 'running', worker_id = ?, "
            "claimed_at = datetime('now') "
            "WHERE id = ? AND status = 'pending'",
            (worker_id, job_id),
        )
        self._conn.commit()

        # Verify we got it (race condition protection)
        cursor = self._conn.execute(
            "SELECT id, batch_id, table_pair, suite_config, priority "
            "FROM job_queue WHERE id = ? AND worker_id = ?",
            (job_id, worker_id),
        )
        claimed = cursor.fetchone()
        if not claimed:
            return self.claim_next_job(worker_id)  # Someone else got it, try next

        return {
            "job_id": claimed[0],
            "batch_id": claimed[1],
            "table_pair": claimed[2],
            "suite_config": json.loads(claimed[3]),
            "priority": claimed[4],
        }

    def complete_job(self, job_id: int, result_json: str):
        """Mark a job as completed."""
        self._conn.execute(
            "UPDATE job_queue SET status = 'completed', completed_at = datetime('now'), "
            "result_json = ? WHERE id = ?",
            (result_json, job_id),
        )
        self._conn.commit()

    def fail_job(self, job_id: int, error: str):
        """Mark a job as failed."""
        self._conn.execute(
            "UPDATE job_queue SET status = 'failed', completed_at = datetime('now'), "
            "result_json = ? WHERE id = ?",
            (json.dumps({"error": error}), job_id),
        )
        self._conn.commit()

    def get_batch_progress(self, batch_id: str) -> dict:
        """Get progress stats for a batch."""
        cursor = self._conn.execute(
            "SELECT status, COUNT(*) FROM job_queue WHERE batch_id = ? GROUP BY status",
            (batch_id,),
        )
        stats = dict(cursor.fetchall())
        total = sum(stats.values())
        return {
            "batch_id": batch_id,
            "total": total,
            "pending": stats.get("pending", 0),
            "running": stats.get("running", 0),
            "completed": stats.get("completed", 0),
            "failed": stats.get("failed", 0),
            "pct_done": round((stats.get("completed", 0) + stats.get("failed", 0)) / max(total, 1) * 100, 1),
        }

    def close(self):
        self._conn.close()

    # ── Validation Metadata CRUD ─────────────────────────────────────────────

    def get_all_metadata(self, group: str = "", active_only: bool = True) -> list[dict]:
        """List all validation metadata entries."""
        query = "SELECT * FROM validation_metadata WHERE 1=1"
        params = []
        if active_only:
            query += " AND active = 1"
        if group:
            query += " AND group_name = ?"
            params.append(group)
        query += " ORDER BY priority DESC, group_name, source_table"
        cursor = self._conn.execute(query, params)
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def get_metadata_by_id(self, meta_id: int) -> dict | None:
        cursor = self._conn.execute(
            "SELECT * FROM validation_metadata WHERE id = ?", (meta_id,)
        )
        cols = [d[0] for d in cursor.description]
        row = cursor.fetchone()
        return dict(zip(cols, row)) if row else None

    def create_metadata(self, entry: dict) -> int:
        """Insert a new validation metadata entry. Returns the new ID."""
        allowed = {
            "group_name", "source_connection", "source_table",
            "target_connection", "target_table", "join_keys", "check_types",
            "strategy", "priority", "tolerance", "where_clause",
            "ignore_columns", "timestamp_column", "schedule", "active",
            "tags", "notes",
        }
        filtered = {k: v for k, v in entry.items() if k in allowed}
        cols = ", ".join(filtered.keys())
        placeholders = ", ".join("?" * len(filtered))
        cursor = self._conn.execute(
            f"INSERT INTO validation_metadata ({cols}) VALUES ({placeholders})",
            list(filtered.values()),
        )
        self._conn.commit()
        return cursor.lastrowid

    def update_metadata(self, meta_id: int, updates: dict) -> bool:
        """Update an existing metadata entry."""
        allowed = {
            "group_name", "source_connection", "source_table",
            "target_connection", "target_table", "join_keys", "check_types",
            "strategy", "priority", "tolerance", "where_clause",
            "ignore_columns", "timestamp_column", "schedule", "active",
            "tags", "notes",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return False
        sets = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [meta_id]
        self._conn.execute(
            f"UPDATE validation_metadata SET {sets}, updated_at = datetime('now') WHERE id = ?",
            values,
        )
        self._conn.commit()
        return True

    def delete_metadata(self, meta_id: int) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM validation_metadata WHERE id = ?", (meta_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def bulk_import_metadata(self, entries: list[dict]) -> int:
        """Bulk import metadata entries (from Excel/CSV). Returns count inserted."""
        count = 0
        for entry in entries:
            try:
                self.create_metadata(entry)
                count += 1
            except Exception as e:
                logger.warning("Skipping metadata entry: %s", e)
        return count

    def get_metadata_groups(self) -> list[str]:
        """List all distinct group names."""
        cursor = self._conn.execute(
            "SELECT DISTINCT group_name FROM validation_metadata ORDER BY group_name"
        )
        return [row[0] for row in cursor.fetchall()]

    def get_metadata_stats(self) -> dict:
        """Summary stats for the metadata table."""
        cursor = self._conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) as active,
                COUNT(DISTINCT group_name) as groups,
                COUNT(DISTINCT source_connection) as source_connections,
                COUNT(DISTINCT target_connection) as target_connections
            FROM validation_metadata
        """)
        row = cursor.fetchone()
        return {
            "total": row[0], "active": row[1], "groups": row[2],
            "source_connections": row[3], "target_connections": row[4],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTIVE STRATEGY SELECTOR — auto-picks optimal comparison strategy per table
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class StrategyRecommendation:
    """Recommended strategy with reasoning."""
    strategy: str
    reason: str
    estimated_speedup: str = ""


def select_optimal_strategy(
    src_conn,
    tgt_conn,
    table_name: str,
    row_count: int | None = None,
    store: IntelligentStore | None = None,
) -> StrategyRecommendation:
    """Auto-select the best comparison strategy based on table characteristics.

    Decision tree:
    1. If we have historical performance data → use the fastest proven strategy
    2. If both are same-instance Teradata → MINUS (server-side, no data transfer)
    3. If row_count < 100K → full (fast enough in memory)
    4. If row_count 100K-1M → hash (90% less network I/O)
    5. If row_count > 1M → streaming with hash-first
    6. If one side is file → duckdb_bridge (handled separately)
    """
    table_upper = table_name.upper()

    # Check historical best strategy
    if store:
        best = store.get_best_strategy(table_upper)
        if best:
            return StrategyRecommendation(
                strategy=best,
                reason=f"Historical best performer for {table_upper}",
                estimated_speedup="proven",
            )

    # Same-instance Teradata check
    src_is_td = (hasattr(src_conn, 'config')
                 and getattr(src_conn.config, 'platform', '') == 'teradata')
    tgt_is_td = (hasattr(tgt_conn, 'config')
                 and getattr(tgt_conn.config, 'platform', '') == 'teradata')

    if src_is_td and tgt_is_td:
        src_dsn = getattr(src_conn.config, 'dsn', '')
        tgt_dsn = getattr(tgt_conn.config, 'dsn', '')
        if src_dsn == tgt_dsn:
            return StrategyRecommendation(
                strategy="minus",
                reason="Same Teradata instance — server-side MINUS (zero data transfer for matching rows)",
                estimated_speedup="10-100x for large tables",
            )

    # Size-based selection
    if row_count is None and src_is_td:
        try:
            row_count = src_conn.get_row_count(table_name)
        except Exception:
            row_count = 500_000  # assume medium

    if row_count is not None:
        if row_count < 100_000:
            return StrategyRecommendation(
                strategy="full",
                reason=f"Small table ({row_count:,} rows) — full in-memory comparison is fast enough",
                estimated_speedup="minimal overhead",
            )
        elif row_count < 1_000_000:
            return StrategyRecommendation(
                strategy="hash",
                reason=f"Medium table ({row_count:,} rows) — hash-first reduces network I/O by 90%+",
                estimated_speedup="5-10x vs full",
            )
        else:
            return StrategyRecommendation(
                strategy="hash",
                reason=f"Large table ({row_count:,} rows) — hash-first with streaming",
                estimated_speedup="10-50x vs full",
            )

    return StrategyRecommendation(
        strategy="hash",
        reason="Default: hash-first pass for unknown table size",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PYRAMID VALIDATION — aggregate check first, drill only on failure
# ═══════════════════════════════════════════════════════════════════════════════

def pyramid_aggregate_check(src_conn, tgt_conn, src_table: str, tgt_table: str,
                            columns: list[str] | None = None,
                            where: str = "") -> dict:
    """Quick aggregate pre-check: COUNT + SUM of numeric columns.

    Returns:
        dict with keys: passed (bool), src_count, tgt_count, agg_match,
        details (list of mismatches if any)
    """
    from ..connectors.base import safe_identifier, safe_table_expr

    clause = f"WHERE {where}" if where else ""
    src_t = safe_table_expr(src_table)
    tgt_t = safe_table_expr(tgt_table)

    # Step 1: Row count comparison
    src_count_df = src_conn.execute_query(f"SELECT COUNT(*) AS CNT FROM {src_t} {clause}")
    tgt_count_df = tgt_conn.execute_query(f"SELECT COUNT(*) AS CNT FROM {tgt_t} {clause}")
    src_count = int(src_count_df.iloc[0, 0])
    tgt_count = int(tgt_count_df.iloc[0, 0])

    if src_count != tgt_count:
        return {
            "passed": False,
            "src_count": src_count,
            "tgt_count": tgt_count,
            "agg_match": False,
            "reason": f"Row count mismatch: src={src_count:,}, tgt={tgt_count:,}",
            "details": [],
        }

    # Step 2: Aggregate comparison on numeric columns
    # Get numeric columns (try to detect from metadata)
    if not columns:
        try:
            meta = tgt_conn.get_metadata(tgt_table)
            numeric_types = {'NUMBER', 'INTEGER', 'INT', 'BIGINT', 'SMALLINT',
                             'DECIMAL', 'NUMERIC', 'FLOAT', 'DOUBLE', 'REAL'}
            columns = [
                row["COLUMN_NAME"] for _, row in meta.iterrows()
                if any(t in str(row.get("DATA_TYPE", "")).upper() for t in numeric_types)
            ]
        except Exception:
            columns = []

    if not columns:
        # No numeric columns to sum — row counts match, that's our best check
        return {
            "passed": True,
            "src_count": src_count,
            "tgt_count": tgt_count,
            "agg_match": True,
            "reason": "Row counts match, no numeric columns for aggregate check",
            "details": [],
        }

    # Build SUM queries for top N numeric columns (limit to 20 for performance)
    check_cols = columns[:20]
    sum_exprs = ", ".join(
        f'COALESCE(CAST(SUM("{safe_identifier(c)}") AS DECIMAL(38,5)), 0) AS "SUM_{c}"'
        for c in check_cols
    )

    src_agg = src_conn.execute_query(f"SELECT {sum_exprs} FROM {src_t} {clause}")
    tgt_agg = tgt_conn.execute_query(f"SELECT {sum_exprs} FROM {tgt_t} {clause}")

    # Compare aggregates
    mismatches = []
    for col in check_cols:
        sum_col = f"SUM_{col}"
        src_val = float(src_agg[sum_col].iloc[0]) if sum_col in src_agg.columns else 0
        tgt_val = float(tgt_agg[sum_col].iloc[0]) if sum_col in tgt_agg.columns else 0

        if src_val == 0 and tgt_val == 0:
            continue
        # Use relative tolerance of 0.0001 (0.01%) for floating point
        denom = max(abs(src_val), abs(tgt_val), 1)
        diff_pct = abs(src_val - tgt_val) / denom
        if diff_pct > 0.0001:
            mismatches.append({
                "column": col,
                "src_sum": src_val,
                "tgt_sum": tgt_val,
                "diff_pct": round(diff_pct * 100, 4),
            })

    if mismatches:
        return {
            "passed": False,
            "src_count": src_count,
            "tgt_count": tgt_count,
            "agg_match": False,
            "reason": f"Aggregate mismatch on {len(mismatches)} column(s): {', '.join(m['column'] for m in mismatches[:5])}",
            "details": mismatches,
        }

    return {
        "passed": True,
        "src_count": src_count,
        "tgt_count": tgt_count,
        "agg_match": True,
        "reason": f"Row counts match ({src_count:,}) and {len(check_cols)} aggregate(s) match",
        "details": [],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# INCREMENTAL VALIDATION — watermark-based delta
# ═══════════════════════════════════════════════════════════════════════════════

def build_incremental_where(
    table_name: str,
    timestamp_column: str,
    store: IntelligentStore,
    existing_where: str = "",
    dsn: str = "",
) -> tuple[str, bool]:
    """Build a WHERE clause for incremental validation.

    Returns:
        (where_clause, is_incremental) — the enriched WHERE and whether watermark was applied
    """
    watermark = store.get_watermark(table_name, dsn)

    if not watermark:
        logger.info("No watermark for %s — running full validation", table_name)
        return existing_where, False

    # Build incremental filter
    ts_filter = f'"{timestamp_column}" > TIMESTAMP \'{watermark}\''

    if existing_where:
        combined = f"({existing_where}) AND {ts_filter}"
    else:
        combined = ts_filter

    logger.info("Incremental validation for %s: WHERE %s > '%s'",
                table_name, timestamp_column, watermark)
    return combined, True


def get_current_watermark(conn, table_name: str, timestamp_column: str,
                          where: str = "") -> str | None:
    """Get the max timestamp value to use as the new watermark."""
    from ..connectors.base import safe_identifier, safe_table_expr
    clause = f"WHERE {where}" if where else ""
    try:
        df = conn.execute_query(
            f'SELECT MAX("{safe_identifier(timestamp_column)}") AS MAX_TS '
            f'FROM {safe_table_expr(table_name)} {clause}'
        )
        val = df.iloc[0, 0]
        return str(val) if val is not None else None
    except Exception as e:
        logger.warning("Could not get watermark for %s.%s: %s", table_name, timestamp_column, e)
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# STATISTICAL ANOMALY DETECTION — baseline comparison
# ═══════════════════════════════════════════════════════════════════════════════

def detect_anomalies(
    current_metrics: dict,
    table_name: str,
    store: IntelligentStore,
) -> list[dict]:
    """Compare current run metrics against historical baseline.

    Returns list of anomalies detected (empty if all normal).
    """
    profile = store.get_profile(table_name)
    if not profile or not profile.get("row_count"):
        return []  # No baseline yet

    anomalies = []
    historical_count = profile["row_count"]
    current_count = current_metrics.get("src_row_count", 0)

    if historical_count > 0 and current_count > 0:
        change_pct = abs(current_count - historical_count) / historical_count
        # Alert if row count changed by >20% from last known
        if change_pct > 0.20:
            anomalies.append({
                "type": "ROW_COUNT_ANOMALY",
                "severity": "WARNING" if change_pct < 0.5 else "CRITICAL",
                "message": (
                    f"Row count changed significantly: "
                    f"expected ~{historical_count:,}, got {current_count:,} "
                    f"({change_pct*100:.1f}% change)"
                ),
                "expected": historical_count,
                "actual": current_count,
                "change_pct": round(change_pct * 100, 1),
            })

    return anomalies


# ═══════════════════════════════════════════════════════════════════════════════
# ROOT CAUSE CLASSIFICATION — auto-classify failure type
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RootCause:
    """Classification of why a validation failed."""
    classification: str  # MISSING_RECORDS, LATE_ARRIVING, TRANSFORMATION_ERROR, etc.
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    message: str
    auto_retry: bool = False
    retry_delay_s: int = 0


def classify_failure(result_metrics: dict, src_count: int, tgt_count: int) -> RootCause:
    """Auto-classify the root cause of a data validation failure.

    Classifications:
    - MISSING_RECORDS: rows in source not in target (ETL incomplete)
    - EXTRA_RECORDS: rows in target not in source (duplicate injection)
    - TRANSFORMATION_ERROR: keys match but values differ
    - COUNT_MISMATCH: row counts differ significantly
    - LATE_ARRIVING: small number of missing records (likely timing)
    """
    rows_only_src = result_metrics.get("rows_only_in_source", 0)
    rows_only_tgt = result_metrics.get("rows_only_in_target", 0)
    rows_with_diffs = result_metrics.get("rows_with_diffs", 0)

    total_issues = rows_only_src + rows_only_tgt + rows_with_diffs
    if total_issues == 0:
        return RootCause("PASS", "NONE", "No issues detected")

    # Primarily transformation errors (keys match, values differ)
    if rows_with_diffs > 0 and rows_with_diffs > (rows_only_src + rows_only_tgt):
        return RootCause(
            classification="TRANSFORMATION_ERROR",
            severity="HIGH",
            message=(
                f"{rows_with_diffs:,} rows have matching keys but different values. "
                f"Likely a transformation/calculation bug."
            ),
            auto_retry=False,
        )

    # Missing records — source has rows target doesn't
    if rows_only_src > 0 and rows_only_tgt == 0:
        # Small number = likely timing issue
        if src_count > 0 and (rows_only_src / src_count) < 0.01:
            return RootCause(
                classification="LATE_ARRIVING",
                severity="LOW",
                message=(
                    f"{rows_only_src:,} records in source not yet in target "
                    f"(<1% of total). Likely ETL timing — auto-retry recommended."
                ),
                auto_retry=True,
                retry_delay_s=600,  # 10 minutes
            )
        else:
            return RootCause(
                classification="MISSING_RECORDS",
                severity="CRITICAL" if rows_only_src > 1000 else "HIGH",
                message=(
                    f"{rows_only_src:,} records in source missing from target. "
                    f"ETL job may not have completed."
                ),
                auto_retry=True,
                retry_delay_s=1800,  # 30 minutes (wait for ETL to finish)
            )

    # Extra records — target has rows source doesn't
    if rows_only_tgt > 0 and rows_only_src == 0:
        return RootCause(
            classification="EXTRA_RECORDS",
            severity="HIGH",
            message=(
                f"{rows_only_tgt:,} extra records in target not in source. "
                f"Possible duplicate injection or stale data not purged."
            ),
            auto_retry=False,
        )

    # Mixed issues
    if rows_only_src > 0 and rows_only_tgt > 0:
        # If counts are similar, might be a key/ordering issue
        if abs(rows_only_src - rows_only_tgt) < max(rows_only_src, rows_only_tgt) * 0.1:
            return RootCause(
                classification="TRANSFORMATION_ERROR",
                severity="HIGH",
                message=(
                    f"Similar counts of unmatched rows on both sides "
                    f"(src={rows_only_src:,}, tgt={rows_only_tgt:,}). "
                    f"Likely a transformation or type-casting difference."
                ),
                auto_retry=False,
            )
        return RootCause(
            classification="MIXED_ISSUES",
            severity="HIGH",
            message=(
                f"Multiple issue types: {rows_only_src:,} only-in-src, "
                f"{rows_only_tgt:,} only-in-tgt, {rows_with_diffs:,} value diffs."
            ),
            auto_retry=False,
        )

    return RootCause(
        classification="UNKNOWN",
        severity="MEDIUM",
        message=f"Unclassified failure: {total_issues:,} total issues",
        auto_retry=False,
    )
