"""Automatic data profiler and test-suite generator.

Industry reference: Great Expectations ``suite scaffold``, Soda ``scan --profile``.

Connects to a table, profiles every column, and auto-generates a YAML test suite
with appropriate checks and thresholds. This eliminates the need to manually
write test definitions for routine validations.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from ..connectors.base import BaseConnector, safe_identifier

logger = logging.getLogger(__name__)


@dataclass
class ColumnProfile:
    """Statistical profile for a single column."""
    name: str
    data_type: str
    nullable: str
    row_count: int = 0
    null_count: int = 0
    null_pct: float = 0.0
    distinct_count: int = 0
    distinct_pct: float = 0.0
    # numeric
    min_val: float | None = None
    max_val: float | None = None
    mean_val: float | None = None
    stddev_val: float | None = None
    # string
    min_length: int | None = None
    max_length: int | None = None
    avg_length: float | None = None
    empty_count: int = 0


@dataclass
class TableProfile:
    """Full profile for a table."""
    table: str
    row_count: int = 0
    column_count: int = 0
    columns: list[ColumnProfile] = field(default_factory=list)
    duplicate_key_candidates: list[str] = field(default_factory=list)


def profile_table(
    conn: BaseConnector,
    table: str,
    sample_pct: float = 100.0,
    max_distinct_check: int = 1_000_000,
) -> TableProfile:
    """Profile a table — gathers statistics for every column.

    Parameters
    ----------
    conn : an open connector
    table : fully-qualified table name
    sample_pct : percentage of rows to sample (100 = full table)
    max_distinct_check : skip distinct count if row_count exceeds this
    """
    table = safe_identifier(table)
    logger.info("Profiling table %s (sample %.0f%%)", table, sample_pct)

    # Row count
    rc_df = conn.execute_query(f"SELECT COUNT(*) AS cnt FROM {table}")
    row_count = int(rc_df.iloc[0, 0])

    # Metadata
    meta = conn.get_metadata(table)
    column_count = len(meta)

    # Build a single profiling query (one pass over the data)
    sample_clause = ""
    if sample_pct < 100:
        sample_clause = f"SAMPLE {int(sample_pct * row_count / 100)}"

    expressions = []
    col_names = []
    for _, row in meta.iterrows():
        col = row["COLUMN_NAME"]
        dtype = str(row.get("DATA_TYPE", "")).upper()
        col_names.append(col)

        safe_col = f'"{safe_identifier(col)}"'

        # Always: null count
        expressions.append(f'SUM(CASE WHEN {safe_col} IS NULL THEN 1 ELSE 0 END) AS "null_{col}"')

        # Distinct (if table is not too large)
        if row_count <= max_distinct_check:
            expressions.append(f'COUNT(DISTINCT {safe_col}) AS "dist_{col}"')

        # Numeric columns
        if any(t in dtype for t in ("INT", "NUM", "DEC", "FLOAT", "DOUBLE", "REAL", "BIGINT")):
            expressions.append(f'MIN({safe_col}) AS "min_{col}"')
            expressions.append(f'MAX({safe_col}) AS "max_{col}"')
            expressions.append(f'AVG(CAST({safe_col} AS FLOAT)) AS "mean_{col}"')
            expressions.append(f'STDDEV_SAMP(CAST({safe_col} AS FLOAT)) AS "std_{col}"')

        # String columns
        if any(t in dtype for t in ("CHAR", "VARCHAR", "TEXT", "STRING")):
            expressions.append(
                f"SUM(CASE WHEN TRIM(CAST({safe_col} AS VARCHAR(1000))) = '' "
                f"THEN 1 ELSE 0 END) AS \"empty_{col}\""
            )
            expressions.append(f'MIN(CHARACTERS({safe_col})) AS "minlen_{col}"')
            expressions.append(f'MAX(CHARACTERS({safe_col})) AS "maxlen_{col}"')
            expressions.append(f'AVG(CAST(CHARACTERS({safe_col}) AS FLOAT)) AS "avglen_{col}"')

    if not expressions:
        return TableProfile(table=table, row_count=row_count, column_count=column_count)

    query = f"SELECT {', '.join(expressions)} FROM {table} {sample_clause}"
    try:
        stats_df = conn.execute_query(query)
    except Exception as e:
        logger.error("Profiling query failed: %s", e)
        return TableProfile(table=table, row_count=row_count, column_count=column_count)

    stats = stats_df.iloc[0]

    # Parse results into ColumnProfiles
    profiles = []
    for _, row in meta.iterrows():
        col = row["COLUMN_NAME"]
        dtype = str(row.get("DATA_TYPE", "")).upper()
        nullable = str(row.get("NULLABLE", "Y"))

        nc = int(stats.get(f"null_{col}", 0) or 0)
        dc = int(stats.get(f"dist_{col}", 0) or 0) if row_count <= max_distinct_check else -1

        cp = ColumnProfile(
            name=col,
            data_type=dtype,
            nullable=nullable,
            row_count=row_count,
            null_count=nc,
            null_pct=round(nc / row_count * 100, 2) if row_count else 0,
            distinct_count=dc,
            distinct_pct=round(dc / row_count * 100, 2) if row_count and dc >= 0 else 0,
        )

        # Numeric stats
        if any(t in dtype for t in ("INT", "NUM", "DEC", "FLOAT", "DOUBLE", "REAL", "BIGINT")):
            cp.min_val = _safe_float(stats.get(f"min_{col}"))
            cp.max_val = _safe_float(stats.get(f"max_{col}"))
            cp.mean_val = _safe_float(stats.get(f"mean_{col}"))
            cp.stddev_val = _safe_float(stats.get(f"std_{col}"))

        # String stats
        if any(t in dtype for t in ("CHAR", "VARCHAR", "TEXT", "STRING")):
            cp.empty_count = int(stats.get(f"empty_{col}", 0) or 0)
            cp.min_length = _safe_int(stats.get(f"minlen_{col}"))
            cp.max_length = _safe_int(stats.get(f"maxlen_{col}"))
            cp.avg_length = _safe_float(stats.get(f"avglen_{col}"))

        profiles.append(cp)

    # Identify unique-key candidates (columns with 100% distinct, 0% null)
    key_candidates = [
        p.name for p in profiles
        if p.distinct_pct == 100.0 and p.null_pct == 0.0
    ]

    tp = TableProfile(
        table=table,
        row_count=row_count,
        column_count=column_count,
        columns=profiles,
        duplicate_key_candidates=key_candidates,
    )
    logger.info(
        "Profile complete: %s — %d rows, %d cols, %d key candidates",
        table, row_count, column_count, len(key_candidates),
    )
    return tp


def _safe_float(val) -> float | None:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    try:
        return round(float(val), 5)
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ── Suite Generator ───────────────────────────────────────────────────────────

def generate_suite_from_profile(
    source_table: str,
    target_table: str,
    profile: TableProfile,
    source_platform: str = "teradata",
    target_platform: str = "teradata",
    suite_name: str | None = None,
) -> dict:
    """Auto-generate a YAML-compatible test suite dict from a table profile.

    This is the "expectation scaffold" feature — it creates a complete
    validation suite with intelligent thresholds derived from the data.
    """
    suite_name = suite_name or f"auto_{profile.table.replace('.', '_').lower()}"

    checks = []

    # 1. Row count with 5% tolerance (accommodates normal daily variation)
    checks.append({
        "type": "row_count",
        "tolerance": 0.05,
    })

    # 2. Metadata check
    checks.append({
        "type": "metadata",
        "ignore_columns": ["DL_INSERT_TS", "DL_UPDATE_TS"],
    })

    # 3. Null checks on non-nullable columns
    non_nullable = [p.name for p in profile.columns if p.nullable.upper() == "N"]
    if non_nullable:
        checks.append({
            "type": "null_check",
            "columns": non_nullable,
        })

    # 4. Duplicate check on key candidates
    if profile.duplicate_key_candidates:
        checks.append({
            "type": "duplicate",
            "columns": profile.duplicate_key_candidates,
        })

    # 5. Data comparison (if keys are available)
    if profile.duplicate_key_candidates:
        checks.append({
            "type": "data",
            "join_keys": profile.duplicate_key_candidates[:3],  # max 3 keys
            "strategy": "hash",
            "column_drill_down": True,
        })

    # 6. Aggregate checks on all numeric columns
    numeric_cols = [
        p.name for p in profile.columns
        if p.min_val is not None
    ]
    if numeric_cols:
        checks.append({
            "type": "aggregate",
            "columns": numeric_cols,
            "functions": ["MIN", "MAX", "SUM", "AVG"],
        })

    suite = {
        "test_suite": suite_name,
        "source": {"platform": source_platform, "table": source_table},
        "target": {"platform": target_platform, "table": target_table},
        "checks": checks,
    }

    return suite


def generate_suite_yaml(
    source_table: str,
    target_table: str,
    profile: TableProfile,
    output_path: str | Path | None = None,
    **kwargs,
) -> str:
    """Generate YAML string (and optionally write to file)."""
    suite_dict = generate_suite_from_profile(
        source_table, target_table, profile, **kwargs
    )
    yaml_str = yaml.dump(suite_dict, default_flow_style=False, sort_keys=False)

    if output_path:
        Path(output_path).write_text(yaml_str)
        logger.info("Generated suite written to %s", output_path)

    return yaml_str
