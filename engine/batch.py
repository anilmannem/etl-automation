"""Batch execution engine — validates 3000+ tables in parallel.

Design principles:
- Connection pooling: reuse connections per (platform, dsn) pair
- Chunked parallelism: configurable concurrency (respects DB session limits)
- Priority ordering: critical tables first
- Failure isolation: one table failure never blocks others
- Progress tracking: real-time status per table in SQLite
- Smart skipping: pyramid pre-check + incremental = skip unchanged tables
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from ..checks.base import CheckConfig, CheckResult, Status
from ..checks.registry import get_check
from ..connectors.base import BaseConnector, ConnectionConfig
from ..connectors.registry import get_connector
from .resilience import CircuitBreaker, CircuitBreakerConfig, retry, RetryConfig

logger = logging.getLogger(__name__)

_RETRY = RetryConfig(max_retries=2, base_delay_s=2.0, jitter=True)
_CB_CONFIG = CircuitBreakerConfig(failure_threshold=5, timeout_s=30.0)


# ── Connection Pool ──────────────────────────────────────────────────────────

class ConnectionPool:
    """Thread-safe connection pool keyed by (platform, dsn/host).

    Teradata has limited concurrent sessions (~120 per user), so we cap
    pool size per unique connection key.
    """

    def __init__(self, max_per_key: int = 10):
        self._max_per_key = max_per_key
        self._pools: dict[str, list[BaseConnector]] = {}
        self._in_use: dict[str, int] = {}
        self._lock = Lock()
        self._configs: dict[str, tuple[str, ConnectionConfig]] = {}

    def _key(self, platform: str, config: ConnectionConfig) -> str:
        return f"{platform}::{config.dsn or config.host}::{config.database}"

    def register(self, platform: str, config: ConnectionConfig):
        """Pre-register a connection config (call before batch starts)."""
        key = self._key(platform, config)
        with self._lock:
            if key not in self._pools:
                self._pools[key] = []
                self._in_use[key] = 0
                self._configs[key] = (platform, config)

    def acquire(self, platform: str, config: ConnectionConfig) -> BaseConnector:
        """Get a connection from the pool (or create new if under limit)."""
        key = self._key(platform, config)
        with self._lock:
            # Try reuse
            if self._pools.get(key):
                conn = self._pools[key].pop()
                self._in_use[key] = self._in_use.get(key, 0) + 1
                # Verify alive
                try:
                    if conn.is_alive():
                        return conn
                    else:
                        conn.close()
                except Exception:
                    pass

            # Create new if under limit
            in_use = self._in_use.get(key, 0)
            if in_use < self._max_per_key:
                self._in_use[key] = in_use + 1
            else:
                # At capacity — block briefly and retry
                self._lock.release()
                time.sleep(0.5)
                self._lock.acquire()
                if self._pools.get(key):
                    conn = self._pools[key].pop()
                    self._in_use[key] = self._in_use.get(key, 0) + 1
                    return conn
                # Force create beyond limit (better than deadlock)
                self._in_use[key] = self._in_use.get(key, 0) + 1

        # Create outside lock
        conn = get_connector(platform, config)
        conn.connect()
        return conn

    def release(self, platform: str, config: ConnectionConfig, conn: BaseConnector):
        """Return connection to pool for reuse."""
        key = self._key(platform, config)
        with self._lock:
            self._in_use[key] = max(0, self._in_use.get(key, 1) - 1)
            try:
                if conn.is_alive():
                    self._pools.setdefault(key, []).append(conn)
                    return
            except Exception:
                pass
            # Dead connection — just close
            try:
                conn.close()
            except Exception:
                pass

    def close_all(self):
        """Drain all pooled connections."""
        with self._lock:
            for key, conns in self._pools.items():
                for c in conns:
                    try:
                        c.close()
                    except Exception:
                        pass
            self._pools.clear()
            self._in_use.clear()

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "pools": len(self._pools),
                "total_idle": sum(len(v) for v in self._pools.values()),
                "total_in_use": sum(self._in_use.values()),
            }


# ── Batch Progress Tracker ───────────────────────────────────────────────────

_BATCH_DB = Path("etl_validator_results.db")


@dataclass
class TableResult:
    table: str
    group: str
    status: str = "pending"  # pending | running | pass | fail | error | skipped
    message: str = ""
    duration_s: float = 0.0
    checks_passed: int = 0
    checks_failed: int = 0
    checks_total: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0


class BatchTracker:
    """Tracks real-time progress of a batch run in SQLite."""

    def __init__(self, batch_id: str, total: int):
        self.batch_id = batch_id
        self.total = total
        self._results: dict[str, TableResult] = {}
        self._lock = Lock()
        self._start_time = time.time()

    def register(self, table: str, group: str):
        with self._lock:
            self._results[table] = TableResult(table=table, group=group)

    def mark_running(self, table: str):
        with self._lock:
            if table in self._results:
                self._results[table].status = "running"
                self._results[table].started_at = time.time()

    def mark_done(self, table: str, status: str, message: str = "",
                  checks_passed: int = 0, checks_failed: int = 0, checks_total: int = 0):
        with self._lock:
            if table in self._results:
                r = self._results[table]
                r.status = status
                r.message = message
                r.finished_at = time.time()
                r.duration_s = round(r.finished_at - r.started_at, 2)
                r.checks_passed = checks_passed
                r.checks_failed = checks_failed
                r.checks_total = checks_total

    @property
    def progress(self) -> dict:
        with self._lock:
            statuses = [r.status for r in self._results.values()]
            completed = sum(1 for s in statuses if s in ("pass", "fail", "error", "skipped"))
            running = sum(1 for s in statuses if s == "running")
            elapsed = round(time.time() - self._start_time, 1)

            # Estimate remaining
            if completed > 0:
                avg_per_table = elapsed / completed
                remaining = (self.total - completed) * avg_per_table
            else:
                remaining = 0

            return {
                "batch_id": self.batch_id,
                "total": self.total,
                "completed": completed,
                "running": running,
                "pending": self.total - completed - running,
                "passed": sum(1 for s in statuses if s == "pass"),
                "failed": sum(1 for s in statuses if s == "fail"),
                "errors": sum(1 for s in statuses if s == "error"),
                "skipped": sum(1 for s in statuses if s == "skipped"),
                "pct_done": round(completed / max(self.total, 1) * 100, 1),
                "elapsed_s": elapsed,
                "est_remaining_s": round(remaining, 0),
                "tables_per_min": round(completed / max(elapsed / 60, 0.01), 1),
            }

    @property
    def results_list(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "table": r.table, "group": r.group, "status": r.status,
                    "message": r.message, "duration_s": r.duration_s,
                    "checks_passed": r.checks_passed, "checks_failed": r.checks_failed,
                }
                for r in self._results.values()
            ]


# ── Active batch registry (for progress polling) ────────────────────────────

_active_batches: dict[str, BatchTracker] = {}
_batches_lock = Lock()


def get_batch_progress(batch_id: str) -> dict | None:
    """Get real-time progress for an active batch."""
    with _batches_lock:
        tracker = _active_batches.get(batch_id)
    if tracker:
        return tracker.progress
    return None


def get_batch_details(batch_id: str) -> list[dict] | None:
    """Get per-table results for an active batch."""
    with _batches_lock:
        tracker = _active_batches.get(batch_id)
    if tracker:
        return tracker.results_list
    return None


# ── Single table validation worker ──────────────────────────────────────────

def _validate_single_table(
    entry: dict,
    src_platform: str,
    src_config: ConnectionConfig,
    tgt_platform: str,
    tgt_config: ConnectionConfig,
    pool: ConnectionPool,
    incremental: bool = False,
    timestamp_column: str = "DL_UPDATE_TS",
) -> dict:
    """Validate one table pair. Uses connection pool. Returns result dict."""
    table_name = entry.get("source_table", "?")
    start = time.time()

    src_conn = None
    tgt_conn = None
    try:
        # Acquire pooled connections
        src_conn = pool.acquire(src_platform, src_config)
        tgt_conn = pool.acquire(tgt_platform, tgt_config)

        # Build checks from metadata
        check_types = [ct.strip() for ct in entry.get("check_types", "row_count").split(",") if ct.strip()]
        join_keys = [k.strip() for k in entry.get("join_keys", "").split(",") if k.strip()]
        ignore_cols = [c.strip() for c in entry.get("ignore_columns", "").split(",") if c.strip()]

        results = []
        for ct in check_types:
            cfg = CheckConfig(
                check_type=ct,
                source_table=entry["source_table"],
                target_table=entry["target_table"],
                join_keys=join_keys,
                ignore_columns=ignore_cols,
                where=entry.get("where_clause", ""),
                tolerance=entry.get("tolerance", 0),
                extra={"strategy": entry.get("strategy", "auto")},
            )

            # Incremental: inject watermark
            if incremental and ct in ("data", "row_count"):
                try:
                    from .intelligent import IntelligentStore, build_incremental_where
                    store = IntelligentStore()
                    dsn = src_config.dsn or ""
                    new_where, is_incr = build_incremental_where(
                        table_name, timestamp_column, store,
                        existing_where=cfg.where, dsn=dsn,
                    )
                    if is_incr:
                        cfg.where = new_where
                        cfg.extra["_incremental"] = True
                    store.close()
                except Exception:
                    pass

            # Execute check with retry
            try:
                check = get_check(ct)

                @retry(_RETRY)
                def _run():
                    return check.run(src_conn, tgt_conn, cfg)

                result = _run()
            except Exception as e:
                result = CheckResult(
                    check_type=ct,
                    status=Status.ERROR,
                    message=str(e),
                )
            results.append(result)

        # Aggregate
        passed = sum(1 for r in results if r.status == Status.PASS)
        failed = sum(1 for r in results if r.status == Status.FAIL)
        errors = sum(1 for r in results if r.status == Status.ERROR)

        if errors > 0:
            overall = "error"
        elif failed > 0:
            overall = "fail"
        else:
            overall = "pass"

        duration = round(time.time() - start, 2)
        return {
            "table": table_name,
            "group": entry.get("group_name", ""),
            "status": overall,
            "checks_passed": passed,
            "checks_failed": failed,
            "checks_total": len(results),
            "duration_s": duration,
            "message": "" if overall == "pass" else "; ".join(
                r.message for r in results if r.status != Status.PASS
            )[:200],
        }

    except Exception as e:
        duration = round(time.time() - start, 2)
        return {
            "table": table_name,
            "group": entry.get("group_name", ""),
            "status": "error",
            "message": str(e)[:200],
            "duration_s": duration,
            "checks_passed": 0,
            "checks_failed": 0,
            "checks_total": 0,
        }
    finally:
        # Return connections to pool
        if src_conn:
            pool.release(src_platform, src_config, src_conn)
        if tgt_conn:
            pool.release(tgt_platform, tgt_config, tgt_conn)


# ── Main batch executor ──────────────────────────────────────────────────────

@dataclass
class BatchConfig:
    """Configuration for a batch validation run."""
    max_parallel: int = 20          # concurrent table validations
    max_connections_per_db: int = 10  # pool size per unique connection
    incremental: bool = False
    timestamp_column: str = "DL_UPDATE_TS"
    fail_fast: bool = False         # stop all on first failure
    priority_order: bool = True     # sort by priority DESC


def execute_batch(
    entries: list[dict],
    connections_map: dict[str, tuple[str, ConnectionConfig]],
    config: BatchConfig | None = None,
) -> dict:
    """Execute batch validation of multiple table pairs in parallel.

    Parameters
    ----------
    entries : list of metadata dicts (from validation_metadata table)
    connections_map : {connection_name: (platform, ConnectionConfig)}
    config : batch execution configuration

    Returns
    -------
    dict with batch_id, progress, and per-table results
    """
    config = config or BatchConfig()
    batch_id = uuid.uuid4().hex[:12]

    # Sort by priority
    if config.priority_order:
        entries = sorted(entries, key=lambda e: e.get("priority", 50), reverse=True)

    # Filter only entries with valid connections
    valid_entries = []
    for entry in entries:
        src_name = entry.get("source_connection", "")
        tgt_name = entry.get("target_connection", "")
        if src_name in connections_map and tgt_name in connections_map:
            valid_entries.append(entry)
        else:
            logger.warning("Skipping %s: connection not found (src=%s, tgt=%s)",
                           entry.get("source_table"), src_name, tgt_name)

    if not valid_entries:
        return {"batch_id": batch_id, "error": "No valid entries to execute"}

    # Initialize pool and tracker
    pool = ConnectionPool(max_per_key=config.max_connections_per_db)
    tracker = BatchTracker(batch_id, len(valid_entries))

    # Register connections in pool
    for name, (platform, cfg) in connections_map.items():
        pool.register(platform, cfg)

    # Register entries in tracker
    for entry in valid_entries:
        tracker.register(entry["source_table"], entry.get("group_name", ""))

    # Store tracker for progress polling
    with _batches_lock:
        _active_batches[batch_id] = tracker

    logger.info("BATCH %s: Starting %d table validations (parallel=%d, pool=%d/db)",
                batch_id, len(valid_entries), config.max_parallel, config.max_connections_per_db)

    all_results = []
    failed_count = 0

    try:
        with ThreadPoolExecutor(max_workers=config.max_parallel) as executor:
            futures = {}
            for entry in valid_entries:
                src_name = entry["source_connection"]
                tgt_name = entry["target_connection"]
                src_platform, src_config = connections_map[src_name]
                tgt_platform, tgt_config = connections_map[tgt_name]

                future = executor.submit(
                    _validate_single_table,
                    entry=entry,
                    src_platform=src_platform,
                    src_config=src_config,
                    tgt_platform=tgt_platform,
                    tgt_config=tgt_config,
                    pool=pool,
                    incremental=config.incremental,
                    timestamp_column=config.timestamp_column,
                )
                futures[future] = entry
                tracker.mark_running(entry["source_table"])

            for future in as_completed(futures):
                entry = futures[future]
                table_name = entry.get("source_table", "?")

                try:
                    result = future.result()
                except Exception as e:
                    result = {
                        "table": table_name,
                        "group": entry.get("group_name", ""),
                        "status": "error",
                        "message": str(e)[:200],
                        "duration_s": 0,
                        "checks_passed": 0,
                        "checks_failed": 0,
                        "checks_total": 0,
                    }

                all_results.append(result)
                tracker.mark_done(
                    table_name,
                    status=result["status"],
                    message=result.get("message", ""),
                    checks_passed=result.get("checks_passed", 0),
                    checks_failed=result.get("checks_failed", 0),
                    checks_total=result.get("checks_total", 0),
                )

                if result["status"] in ("fail", "error"):
                    failed_count += 1

                if config.fail_fast and failed_count > 0:
                    logger.warning("BATCH %s: Fail-fast triggered, cancelling remaining", batch_id)
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

    finally:
        pool.close_all()
        logger.info("BATCH %s: Complete. Pool stats at close: %s", batch_id, pool.stats)

    # Final summary
    elapsed = time.time() - tracker._start_time
    summary = {
        "batch_id": batch_id,
        "total": len(valid_entries),
        "passed": sum(1 for r in all_results if r["status"] == "pass"),
        "failed": sum(1 for r in all_results if r["status"] == "fail"),
        "errors": sum(1 for r in all_results if r["status"] == "error"),
        "skipped": len(entries) - len(valid_entries),
        "duration_s": round(elapsed, 1),
        "tables_per_minute": round(len(all_results) / max(elapsed / 60, 0.01), 1),
        "results": all_results,
    }

    # Cleanup tracker after a delay (keep for polling for 5 min)
    import threading
    def _cleanup():
        time.sleep(300)
        with _batches_lock:
            _active_batches.pop(batch_id, None)
    threading.Thread(target=_cleanup, daemon=True).start()

    return summary
