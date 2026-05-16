"""FastAPI backend for ETL Validator React UI."""
from __future__ import annotations

import datetime
import json
import logging
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import uuid

import yaml
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from etl_validator.connectors.base import ConnectionConfig
from etl_validator.connectors.registry import get_connector
from etl_validator.engine.executor import SuiteResult, execute_suite
from etl_validator.engine.result_store import ResultStore
from etl_validator.engine.suite_loader import load_suite

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(title="ETL Validator API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Connection Store (SQLite) ────────────────────────────────────────────────

_CONN_DB = Path("etl_validator_connections.db")


def _conn_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(_CONN_DB))
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE IF NOT EXISTS connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL,
            dsn TEXT DEFAULT '',
            host TEXT DEFAULT '',
            port INTEGER DEFAULT 0,
            username TEXT DEFAULT '',
            password TEXT DEFAULT '',
            database_name TEXT DEFAULT '',
            schema_name TEXT DEFAULT '',
            file_path TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    db.commit()
    return db


# ── Pydantic Models ──────────────────────────────────────────────────────────

class SavedConnection(BaseModel):
    name: str
    platform: str
    dsn: str = ""
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    database_name: str = ""
    schema_name: str = ""
    file_path: str = ""


class CheckSpec(BaseModel):
    type: str
    strategy: str = "hash"
    sample_pct: float = 10.0
    column_drill_down: bool = True
    join_keys: list[str] = []
    columns: list[str] = []
    functions: list[str] = ["MIN", "MAX", "AVG", "SUM"]


class AdhocRequest(BaseModel):
    source_connection_id: int | None = None
    source_file_path: str = ""
    source_table: str = ""
    target_connection_id: int | None = None
    target_file_path: str = ""
    target_table: str = ""
    checks: list[CheckSpec]
    where: str = ""
    suite_name: str = ""
    parallel: bool = False
    max_workers: int = 4
    fail_fast: bool = False
    batch_id: str = ""
    # Intelligent features
    incremental: bool = False
    timestamp_column: str = "DL_UPDATE_TS"


class HistoryQuery(BaseModel):
    suite: str = ""
    days: int = 30


# ── Helpers ───────────────────────────────────────────────────────────────────

def _suite_result_to_dict(result: SuiteResult) -> dict:
    """Serialize SuiteResult to JSON-safe dict."""
    summary = result.summary_dict()
    checks = []
    for r in result.results:
        check_dict = {
            "check_type": r.check_type,
            "status": str(r.status),
            "message": r.message,
            "metrics": r.metrics,
        }
        if r.details is not None and len(r.details) > 0:
            check_dict["details"] = json.loads(
                r.details.head(100).to_json(orient="records")
            )
            check_dict["details_total"] = len(r.details)
        else:
            check_dict["details"] = []
            check_dict["details_total"] = 0
        checks.append(check_dict)

    timings = []
    for t in result.timings:
        timings.append({
            "check_type": t.check_type,
            "duration_s": round(t.duration_s, 3),
        })

    return {
        "run_id": result.run_id,
        "suite_name": result.suite_name,
        "summary": summary,
        "checks": checks,
        "timings": timings,
    }


def _get_saved_connection(conn_id: int) -> dict:
    """Fetch a saved connection by ID."""
    db = _conn_db()
    row = db.execute("SELECT * FROM connections WHERE id = ?", (conn_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Connection {conn_id} not found")
    return dict(row)


def _config_from_saved(conn: dict) -> ConnectionConfig:
    """Build a ConnectionConfig from a saved connection dict."""
    platform = conn["platform"].lower()
    if platform == "csv":
        return ConnectionConfig(platform="csv", extra={"file_path": conn["file_path"]})
    return ConnectionConfig(
        platform=platform,
        dsn=conn["dsn"],
        host=conn["host"],
        port=conn["port"],
        user=conn["username"],
        password=conn["password"],
        database=conn["database_name"],
        schema=conn["schema_name"],
    )


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}


# ── Connection Management ────────────────────────────────────────────────────

@app.get("/api/connections")
def list_connections():
    """List all saved connections (passwords masked)."""
    db = _conn_db()
    rows = db.execute("SELECT * FROM connections ORDER BY name").fetchall()
    db.close()
    result = []
    for r in rows:
        d = dict(r)
        d["password"] = "••••••••" if d["password"] else ""
        result.append(d)
    return result


@app.post("/api/connections")
def create_connection(conn: SavedConnection):
    """Create a new saved connection."""
    db = _conn_db()
    try:
        db.execute(
            """INSERT INTO connections (name, platform, dsn, host, port, username, password,
               database_name, schema_name, file_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (conn.name, conn.platform.lower(), conn.dsn, conn.host, conn.port,
             conn.username, conn.password, conn.database_name, conn.schema_name,
             conn.file_path),
        )
        db.commit()
        row_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.close()
        return {"id": row_id, "name": conn.name, "message": "Connection created"}
    except sqlite3.IntegrityError:
        db.close()
        raise HTTPException(status_code=409, detail=f"Connection '{conn.name}' already exists")


@app.put("/api/connections/{conn_id}")
def update_connection(conn_id: int, conn: SavedConnection):
    """Update a saved connection."""
    db = _conn_db()
    existing = db.execute("SELECT id FROM connections WHERE id = ?", (conn_id,)).fetchone()
    if not existing:
        db.close()
        raise HTTPException(status_code=404, detail="Connection not found")
    db.execute(
        """UPDATE connections SET name=?, platform=?, dsn=?, host=?, port=?, username=?,
           password=?, database_name=?, schema_name=?, file_path=?,
           updated_at=datetime('now')
           WHERE id=?""",
        (conn.name, conn.platform.lower(), conn.dsn, conn.host, conn.port,
         conn.username, conn.password, conn.database_name, conn.schema_name,
         conn.file_path, conn_id),
    )
    db.commit()
    db.close()
    return {"id": conn_id, "message": "Connection updated"}


@app.delete("/api/connections/{conn_id}")
def delete_connection(conn_id: int):
    """Delete a saved connection."""
    db = _conn_db()
    db.execute("DELETE FROM connections WHERE id = ?", (conn_id,))
    db.commit()
    db.close()
    return {"message": "Connection deleted"}


@app.post("/api/connections/test")
def test_connection(conn: SavedConnection):
    """Test a connection without saving it."""
    try:
        config = _config_from_saved({
            "platform": conn.platform, "dsn": conn.dsn, "host": conn.host,
            "port": conn.port, "username": conn.username, "password": conn.password,
            "database_name": conn.database_name, "schema_name": conn.schema_name,
            "file_path": conn.file_path,
        })
        connector = get_connector(conn.platform.lower(), config)
        connector.connect()
        alive = connector.is_alive()
        connector.close()
        return {"success": alive, "message": "Connection successful" if alive else "Connection failed"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/api/connections/{conn_id}/test")
def test_saved_connection(conn_id: int):
    """Test an existing saved connection."""
    saved = _get_saved_connection(conn_id)
    try:
        config = _config_from_saved(saved)
        connector = get_connector(saved["platform"].lower(), config)
        connector.connect()
        alive = connector.is_alive()
        connector.close()
        return {"success": alive, "message": "Connection successful" if alive else "Connection failed"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ── CSV Upload ────────────────────────────────────────────────────────────────

_UPLOAD_DIR = Path(tempfile.gettempdir()) / "etl_validator_uploads"
_UPLOAD_DIR.mkdir(exist_ok=True)


@app.post("/api/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    """Accept a CSV file upload and return the temp path."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")
    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    dest = _UPLOAD_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)
    return {"file_path": str(dest), "filename": file.filename, "size": len(content)}


# ── Run Checks ───────────────────────────────────────────────────────────────

def _csv_conn_dict(file_path: str) -> dict:
    """Build a pseudo-connection dict for an uploaded CSV file."""
    return {
        "platform": "csv", "dsn": "", "host": "", "port": 0,
        "username": "", "password": "", "database_name": "",
        "schema_name": "", "file_path": file_path,
    }


@app.post("/api/run")
def run_checks(req: AdhocRequest):
    """Run checks using saved connections or uploaded CSV files."""
    try:
        # Resolve connections — use uploaded file path or saved connection
        if req.source_file_path:
            src_conn = _csv_conn_dict(req.source_file_path)
        else:
            src_conn = _get_saved_connection(req.source_connection_id)
        if req.target_file_path:
            tgt_conn = _csv_conn_dict(req.target_file_path)
        else:
            tgt_conn = _get_saved_connection(req.target_connection_id)

        checks = []
        for c in req.checks:
            check_dict: dict[str, Any] = {"type": c.type}
            if c.type == "data":
                check_dict["strategy"] = c.strategy
                check_dict["column_drill_down"] = c.column_drill_down
                if c.strategy == "sample":
                    check_dict["sample_pct"] = c.sample_pct
            if c.join_keys:
                check_dict["join_keys"] = c.join_keys
            if c.columns:
                check_dict["columns"] = c.columns
            if c.type == "aggregate" and c.functions:
                check_dict["functions"] = c.functions
            checks.append(check_dict)

        suite_data = {
            "test_suite": req.suite_name.strip() or "quick_test",
            "source": {
                "platform": src_conn["platform"],
                "table": req.source_table,
                "dsn": src_conn["dsn"],
                "host": src_conn["host"],
                "port": src_conn["port"],
                "user": src_conn["username"],
                "password": src_conn["password"],
                "database": src_conn["database_name"],
                "schema": src_conn["schema_name"],
                **({"extra": {"file_path": src_conn["file_path"]}} if src_conn["platform"] == "csv" else {}),
            },
            "target": {
                "platform": tgt_conn["platform"],
                "table": req.target_table,
                "dsn": tgt_conn["dsn"],
                "host": tgt_conn["host"],
                "port": tgt_conn["port"],
                "user": tgt_conn["username"],
                "password": tgt_conn["password"],
                "database": tgt_conn["database_name"],
                "schema": tgt_conn["schema_name"],
                **({"extra": {"file_path": tgt_conn["file_path"]}} if tgt_conn["platform"] == "csv" else {}),
            },
            "checks": checks,
        }
        if req.where:
            suite_data["filters"] = {"where": req.where}

        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump(suite_data, f)
            temp_path = f.name

        suite = load_suite(temp_path)
        result = execute_suite(
            suite,
            parallel=req.parallel,
            max_workers=req.max_workers,
            fail_fast=req.fail_fast,
            incremental=req.incremental,
            timestamp_column=req.timestamp_column,
        )

        rs = ResultStore()
        src_label = req.source_file_path or req.source_table
        tgt_label = req.target_file_path or req.target_table
        rs.record_suite(result, batch_id=req.batch_id,
                        source=src_label, target=tgt_label)
        rs.close()

        return _suite_result_to_dict(result)

    except Exception as e:
        log.exception("Check run failed")
        raise HTTPException(status_code=500, detail=str(e))


# ── History ──────────────────────────────────────────────────────────────────

@app.get("/api/history/batch/{batch_id}")
def get_batch_detail(batch_id: str):
    """Reconstruct a consolidated suite result for a batch."""
    rs = ResultStore()
    rows = rs.get_batch(batch_id)
    rs.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")

    # Group rows by run_id (each run_id = one test case)
    from collections import OrderedDict
    tc_map = OrderedDict()
    for row in rows:
        rid = row["run_id"]
        if rid not in tc_map:
            tc_map[rid] = {
                "run_id": rid,
                "source": row.get("source", ""),
                "target": row.get("target", ""),
                "checks": [],
                "passed": 0, "failed": 0, "errors": 0,
                "duration_s": 0.0,
            }
        metrics = json.loads(row["metrics_json"]) if row["metrics_json"] else {}
        details = json.loads(row["details_json"]) if row["details_json"] else []
        status = row["status"]
        dur = row.get("duration_s") or 0.0
        tc_map[rid]["duration_s"] += dur
        if status == "Pass":
            tc_map[rid]["passed"] += 1
        elif status == "Fail":
            tc_map[rid]["failed"] += 1
        else:
            tc_map[rid]["errors"] += 1
        tc_map[rid]["checks"].append({
            "check_type": row["check_type"],
            "status": status,
            "message": row["message"] or "",
            "metrics": metrics,
            "details": details,
            "details_total": len(details),
        })

    test_cases = []
    total_checks = passed_checks = failed_checks = error_checks = 0
    total_duration = 0.0
    for idx, (rid, p) in enumerate(tc_map.items()):
        total = len(p["checks"])
        quality = round((p["passed"] / total) * 100, 1) if total else 0
        tc_status = "Error" if p["errors"] else ("Fail" if p["failed"] else "Pass")
        test_cases.append({
            "index": idx + 1,
            "source_label": p["source"] or "",
            "target_label": p["target"] or "",
            "status": tc_status,
            "result": {
                "run_id": rid,
                "suite_name": rows[0]["suite"],
                "summary": {
                    "total": total,
                    "passed": p["passed"],
                    "failed": p["failed"],
                    "errors": p["errors"],
                    "quality_score": quality,
                    "overall_status": tc_status,
                    "duration_s": round(p["duration_s"], 2),
                },
                "checks": p["checks"],
                "timings": [{"check_type": c["check_type"], "duration_s": 0} for c in p["checks"]],
            },
        })
        total_checks += total
        passed_checks += p["passed"]
        failed_checks += p["failed"]
        error_checks += p["errors"]
        total_duration += p["duration_s"]

    passed_tcs = sum(1 for p in test_cases if p["status"] == "Pass")
    failed_tcs = sum(1 for p in test_cases if p["status"] == "Fail")
    error_tcs = sum(1 for p in test_cases if p["status"] == "Error")
    overall = "Fail" if (failed_tcs > 0 or error_tcs > 0) else "Pass"
    quality_score = round((passed_checks / total_checks) * 100) if total_checks else 0

    return {
        "type": "suite",
        "batch_id": batch_id,
        "suite_name": rows[0]["suite"],
        "started_at": rows[0]["timestamp"],
        "duration_s": round(total_duration, 2),
        "summary": {
            "total_test_cases": len(test_cases),
            "passed_test_cases": passed_tcs,
            "failed_test_cases": failed_tcs,
            "error_test_cases": error_tcs,
            "total_checks": total_checks,
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "error_checks": error_checks,
            "quality_score": quality_score,
            "overall_status": overall,
        },
        "test_cases": test_cases,
    }


@app.get("/api/history/{run_id}")
def get_run_detail(run_id: str):
    """Reconstruct a full result for a past run from stored check rows."""
    rs = ResultStore()
    rows = rs.get_run(run_id)
    rs.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    checks = []
    total_duration = 0.0
    passed = failed = errors = 0
    for row in rows:
        metrics = json.loads(row["metrics_json"]) if row["metrics_json"] else {}
        details = json.loads(row["details_json"]) if row["details_json"] else []
        status = row["status"]
        if status == "Pass":
            passed += 1
        elif status == "Fail":
            failed += 1
        else:
            errors += 1
        dur = row.get("duration_s") or 0.0
        total_duration += dur
        checks.append({
            "check_type": row["check_type"],
            "status": status,
            "message": row["message"] or "",
            "metrics": metrics,
            "details": details,
            "details_total": len(details),
        })

    total = len(checks)
    quality_score = round((passed / total) * 100, 1) if total else 100.0
    overall_status = "Error" if errors else ("Fail" if failed else "Pass")
    timings = [{"check_type": c["check_type"], "duration_s": round(rows[i].get("duration_s") or 0.0, 3)} for i, c in enumerate(checks)]

    return {
        "run_id": run_id,
        "suite_name": rows[0]["suite"],
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "quality_score": quality_score,
            "overall_status": overall_status,
            "duration_s": round(total_duration, 2),
        },
        "checks": checks,
        "timings": timings,
    }


@app.get("/api/history")
def get_history(suite: str = "", days: int = 30):
    """Get test result history."""
    rs = ResultStore()
    df = rs.get_history(suite or None, days)
    rs.close()
    if df.empty:
        return {"results": [], "trend": [], "score_trend": []}

    records = json.loads(df.to_json(orient="records"))

    # Build daily trend
    trend_df = df.copy()
    trend_df["day"] = pd.to_datetime(trend_df["timestamp"]).dt.date.astype(str)
    daily = trend_df.groupby("day").size().reset_index(name="count")
    trend = json.loads(daily.to_json(orient="records"))

    # Build daily quality score trend (MC-style: passed/total per day)
    day_stats = trend_df.groupby("day").apply(
        lambda g: pd.Series({
            "quality_score": round((g["status"] == "Pass").sum() / len(g) * 100, 1) if len(g) > 0 else 100.0,
            "total": len(g),
            "passed": (g["status"] == "Pass").sum(),
            "failed": (g["status"] == "Fail").sum(),
        })
    ).reset_index()
    score_trend = json.loads(day_stats.to_json(orient="records"))

    return {
        "results": records,
        "trend": trend,
        "score_trend": score_trend,
    }


# ── Intelligent Engine Endpoints ─────────────────────────────────────────────

class LineageEntry(BaseModel):
    source_table: str
    target_table: str


class JobQueueRequest(BaseModel):
    batch_id: str
    jobs: list[dict]


@app.get("/api/intelligence/profile/{table_name}")
def get_table_profile(table_name: str):
    """Get the stored profile for a table (row count, strategy performance, watermark)."""
    try:
        from etl_validator.engine.intelligent import IntelligentStore
        store = IntelligentStore()
        profile = store.get_profile(table_name)
        best_strategy = store.get_best_strategy(table_name)
        store.close()
        return {
            "table_name": table_name,
            "profile": profile,
            "best_strategy": best_strategy,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/intelligence/lineage")
def set_lineage(entry: LineageEntry):
    """Define a lineage relationship (source feeds target)."""
    try:
        from etl_validator.engine.intelligent import IntelligentStore
        store = IntelligentStore()
        store.set_lineage(entry.source_table, entry.target_table)
        downstream = store.get_downstream(entry.source_table)
        store.close()
        return {"status": "ok", "downstream_count": len(downstream)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/intelligence/lineage/{table_name}")
def get_lineage(table_name: str):
    """Get upstream and downstream tables for a given table."""
    try:
        from etl_validator.engine.intelligent import IntelligentStore
        store = IntelligentStore()
        upstream = store.get_upstream(table_name)
        downstream = store.get_downstream(table_name)
        store.close()
        return {
            "table_name": table_name,
            "upstream": upstream,
            "downstream": downstream,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/intelligence/queue")
def enqueue_jobs(req: JobQueueRequest):
    """Add validation jobs to the work-stealing queue."""
    try:
        from etl_validator.engine.intelligent import IntelligentStore
        store = IntelligentStore()
        store.enqueue_jobs(req.batch_id, req.jobs)
        progress = store.get_batch_progress(req.batch_id)
        store.close()
        return progress
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/intelligence/queue/{batch_id}")
def get_queue_progress(batch_id: str):
    """Get progress of a queued batch."""
    try:
        from etl_validator.engine.intelligent import IntelligentStore
        store = IntelligentStore()
        progress = store.get_batch_progress(batch_id)
        store.close()
        return progress
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/intelligence/queue/claim/{worker_id}")
def claim_job(worker_id: str):
    """Worker claims the next available job (work-stealing pattern)."""
    try:
        from etl_validator.engine.intelligent import IntelligentStore
        store = IntelligentStore()
        job = store.claim_next_job(worker_id)
        store.close()
        if not job:
            return {"status": "empty", "message": "No pending jobs"}
        return {"status": "claimed", "job": job}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Validation Metadata Management ──────────────────────────────────────────

class MetadataEntry(BaseModel):
    group_name: str = "default"
    source_connection: str
    source_table: str
    target_connection: str
    target_table: str
    join_keys: str = ""
    check_types: str = "data"
    strategy: str = "auto"
    priority: float = 50.0
    tolerance: float = 0.0
    where_clause: str = ""
    ignore_columns: str = "DL_INSERT_TS,DL_UPDATE_TS"
    timestamp_column: str = "DL_UPDATE_TS"
    schedule: str = "daily"
    active: bool = True
    tags: str = ""
    notes: str = ""


class MetadataUpdate(BaseModel):
    group_name: str | None = None
    source_connection: str | None = None
    source_table: str | None = None
    target_connection: str | None = None
    target_table: str | None = None
    join_keys: str | None = None
    check_types: str | None = None
    strategy: str | None = None
    priority: float | None = None
    tolerance: float | None = None
    where_clause: str | None = None
    ignore_columns: str | None = None
    timestamp_column: str | None = None
    schedule: str | None = None
    active: bool | None = None
    tags: str | None = None
    notes: str | None = None


class BulkImportRequest(BaseModel):
    entries: list[dict]


class RunFromMetadataRequest(BaseModel):
    group_name: str = ""
    ids: list[int] = []
    parallel: bool = True
    max_workers: int = 20
    incremental: bool = False
    fail_fast: bool = False


@app.get("/api/metadata")
def list_metadata(group: str = "", active_only: bool = True):
    """List all validation metadata entries."""
    try:
        from etl_validator.engine.intelligent import IntelligentStore
        store = IntelligentStore()
        entries = store.get_all_metadata(group=group, active_only=active_only)
        stats = store.get_metadata_stats()
        groups = store.get_metadata_groups()
        store.close()
        return {"entries": entries, "stats": stats, "groups": groups}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/metadata/{meta_id}")
def get_metadata(meta_id: int):
    """Get a single metadata entry by ID."""
    try:
        from etl_validator.engine.intelligent import IntelligentStore
        store = IntelligentStore()
        entry = store.get_metadata_by_id(meta_id)
        store.close()
        if not entry:
            raise HTTPException(status_code=404, detail="Not found")
        return entry
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/metadata")
def create_metadata(entry: MetadataEntry):
    """Create a new validation metadata entry."""
    try:
        from etl_validator.engine.intelligent import IntelligentStore
        store = IntelligentStore()
        data = entry.model_dump()
        data["active"] = int(data["active"])
        new_id = store.create_metadata(data)
        store.close()
        return {"id": new_id, "status": "created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/metadata/{meta_id}")
def update_metadata(meta_id: int, updates: MetadataUpdate):
    """Update an existing metadata entry."""
    try:
        from etl_validator.engine.intelligent import IntelligentStore
        store = IntelligentStore()
        data = {k: v for k, v in updates.model_dump().items() if v is not None}
        if "active" in data:
            data["active"] = int(data["active"])
        ok = store.update_metadata(meta_id, data)
        store.close()
        if not ok:
            raise HTTPException(status_code=404, detail="Not found or no valid fields")
        return {"status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/metadata/{meta_id}")
def delete_metadata(meta_id: int):
    """Delete a metadata entry."""
    try:
        from etl_validator.engine.intelligent import IntelligentStore
        store = IntelligentStore()
        ok = store.delete_metadata(meta_id)
        store.close()
        if not ok:
            raise HTTPException(status_code=404, detail="Not found")
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/metadata/bulk-import")
def bulk_import_metadata(req: BulkImportRequest):
    """Bulk import metadata entries (from Excel/CSV upload)."""
    try:
        from etl_validator.engine.intelligent import IntelligentStore
        store = IntelligentStore()
        count = store.bulk_import_metadata(req.entries)
        store.close()
        return {"status": "imported", "count": count, "total_submitted": len(req.entries)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/metadata/run")
def run_from_metadata(req: RunFromMetadataRequest):
    """Start batch validation asynchronously.

    Returns batch_id immediately. Poll GET /api/metadata/run/{batch_id} for progress.
    """
    import threading

    try:
        from etl_validator.engine.intelligent import IntelligentStore
        from etl_validator.engine.batch import execute_batch, BatchConfig, BatchTracker, _active_batches, _batches_lock

        store = IntelligentStore()

        # Get entries to run
        if req.ids:
            entries = [store.get_metadata_by_id(i) for i in req.ids]
            entries = [e for e in entries if e]
        else:
            entries = store.get_all_metadata(group=req.group_name, active_only=True)

        if not entries:
            store.close()
            raise HTTPException(status_code=404, detail="No metadata entries found")

        store.close()

        # Build connections map from saved connections DB
        db = _conn_db()
        all_conns = db.execute("SELECT * FROM connections").fetchall()
        db.close()

        connections_map = {}
        for row in all_conns:
            config = ConnectionConfig(
                platform=row["platform"],
                dsn=row["dsn"] or "",
                host=row["host"] or "",
                port=row["port"] or 0,
                user=row["username"] or "",
                password=row["password"] or "",
                database=row["database_name"] or "",
                schema=row["schema_name"] or "",
                extra={"file_path": row["file_path"]} if row["file_path"] else {},
            )
            connections_map[row["name"]] = (row["platform"], config)

        # Configure batch execution
        batch_config = BatchConfig(
            max_parallel=req.max_workers,
            max_connections_per_db=min(req.max_workers, 10),
            incremental=req.incremental,
            fail_fast=req.fail_fast,
            priority_order=True,
        )

        # Pre-register tracker so progress is available immediately
        batch_id = uuid.uuid4().hex[:12]
        tracker = BatchTracker(batch_id, len(entries))
        for entry in entries:
            tracker.register(entry["source_table"], entry.get("group_name", ""))
        with _batches_lock:
            _active_batches[batch_id] = tracker

        # Run batch in background thread
        def _run_batch():
            try:
                execute_batch(entries, connections_map, batch_config, batch_id=batch_id)
            except Exception as e:
                log.exception("Background batch %s failed: %s", batch_id, e)

        thread = threading.Thread(target=_run_batch, daemon=True, name=f"batch-{batch_id}")
        thread.start()

        return {
            "batch_id": batch_id,
            "total": len(entries),
            "status": "started",
            "message": f"Batch started with {len(entries)} tables, {req.max_workers} parallel workers",
        }

    except HTTPException:
        raise
    except Exception as e:
        log.exception("run_from_metadata failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/metadata/run/{batch_id}")
def get_run_progress(batch_id: str):
    """Poll real-time progress of an active batch run."""
    from etl_validator.engine.batch import get_batch_progress, get_batch_details
    progress = get_batch_progress(batch_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Batch not found or already completed")
    return {
        "progress": progress,
        "details": get_batch_details(batch_id),
    }




