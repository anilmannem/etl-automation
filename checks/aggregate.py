"""Aggregate comparison check (MIN/MAX/AVG/SUM + ID boundary + GROUP BY).

Best-in-class features:
- Auto-detect numeric columns when none are specified
- Cardinality-based classification: measures vs identifiers
- Per-column configurable tolerance (not hardcoded 0.001)
- GROUP BY aggregate comparison (SUM/AVG by partition/category)
- STDDEV and COUNT_DISTINCT as additional aggregate functions
- Proper Infinity handling instead of magic 999999.99
- WARNING for near-threshold diffs
- ID boundary checks (MIN/MAX of key columns)
"""

import logging
import math
import re

import pandas as pd

from .base import BaseCheck, CheckConfig, CheckResult, Status
from ..connectors.base import safe_identifier, safe_identifiers, safe_table_expr, quote_identifier

logger = logging.getLogger(__name__)

# Types that are considered numeric across all platforms
_NUMERIC_PATTERNS = re.compile(
    r"^(INT|INTEGER|BIGINT|SMALLINT|TINYINT|BYTEINT"
    r"|FLOAT|DOUBLE|REAL"
    r"|DECIMAL|NUMERIC|DEC|NUMBER"
    r"|INT8|INT16|INT32|INT64|FLOAT32|FLOAT64"
    r")\b",
    re.IGNORECASE,
)

# Cardinality threshold: if distinct_count / row_count > this, the column
# is classified as an identifier (e.g. surrogate key) rather than a measure.
_ID_CARDINALITY_THRESHOLD = 0.9


def _is_numeric_type(dtype: str) -> bool:
    """Return True if a DATA_TYPE string represents a numeric column."""
    dtype = dtype.strip().upper()
    # pandas dtypes
    if dtype in ("INT64", "FLOAT64", "INT32", "FLOAT32", "INT16", "INT8",
                 "UINT8", "UINT16", "UINT32", "UINT64"):
        return True
    # SQL / platform types  (NUMBER(18,2), DECIMAL(10,0), INTEGER, etc.)
    return bool(_NUMERIC_PATTERNS.match(dtype))


# Max rows to sample for cardinality estimation (keeps classification fast
# regardless of table size — O(constant) instead of O(N)).
_CARDINALITY_SAMPLE_SIZE = 10_000


def _get_cardinality(conn, table: str, columns: list[str], where: str = "") -> dict[str, float]:
    """Return {COLUMN: distinct_ratio} for each column (0.0–1.0).

    Samples up to _CARDINALITY_SAMPLE_SIZE rows for efficiency.
    Works with both SQL connectors and CSV (pandas fallback).
    """
    if not columns:
        return {}

    # Try SQL first — use a sampled subquery for performance on large tables
    try:
        tbl = safe_table_expr(table)
        clause = f"WHERE {where}" if where else ""
        count_exprs = ", ".join(
            f'COUNT(DISTINCT "{safe_identifier(c)}") AS "NDV_{c}"' for c in columns
        )
        # Try Teradata SAMPLE syntax first, fall back to ANSI LIMIT
        try:
            sample_query = (
                f'SELECT COUNT(*) AS "TOTAL", {count_exprs} '
                f'FROM (SELECT * FROM {tbl} {clause} SAMPLE {_CARDINALITY_SAMPLE_SIZE}) AS _sample'
            )
            df = conn.execute_query(sample_query)
        except Exception:
            # Fallback: standard SQL with LIMIT (Postgres, DuckDB, etc.)
            sample_query = (
                f'SELECT COUNT(*) AS "TOTAL", {count_exprs} '
                f'FROM (SELECT * FROM {tbl} {clause} LIMIT {_CARDINALITY_SAMPLE_SIZE}) AS _sample'
            )
            df = conn.execute_query(sample_query)

        df.columns = [c.upper() for c in df.columns]
        total = max(int(df["TOTAL"].iloc[0]), 1)
        return {c: int(df[f"NDV_{c}"].iloc[0]) / total for c in columns}
    except (NotImplementedError, Exception):
        pass

    # Pandas fallback (CSV connector) — sample first N rows
    try:
        raw = conn.read_dataframe()
        if len(raw) > _CARDINALITY_SAMPLE_SIZE:
            raw = raw.sample(n=_CARDINALITY_SAMPLE_SIZE, random_state=42)
        total = max(len(raw), 1)
        result = {}
        for c in columns:
            match = [col for col in raw.columns if col.upper() == c.upper()]
            if match:
                result[c] = raw[match[0]].nunique() / total
            else:
                result[c] = 0.0
        return result
    except Exception:
        return {c: 0.0 for c in columns}


class AggregateCheck(BaseCheck):
    name = "aggregate"

    @staticmethod
    def _detect_and_classify_columns(
        src_conn, tgt_conn, config: CheckConfig
    ) -> tuple[list[str], list[str]]:
        """Auto-detect numeric columns and classify into measures vs identifiers.

        Uses cardinality analysis: if a numeric column has >90% unique values
        relative to the row count, it's an identifier (PK/FK/surrogate key).
        Otherwise it's a measure suitable for SUM/AVG/MIN/MAX.

        Returns:
            (measure_columns, identifier_columns)
        """
        src_meta = src_conn.get_metadata(config.source_table)
        tgt_meta = tgt_conn.get_metadata(config.target_table)

        ignore_upper = {c.upper() for c in config.ignore_columns}

        src_numeric = {
            row["COLUMN_NAME"].upper()
            for _, row in src_meta.iterrows()
            if _is_numeric_type(row["DATA_TYPE"]) and row["COLUMN_NAME"].upper() not in ignore_upper
        }
        tgt_numeric = {
            row["COLUMN_NAME"].upper()
            for _, row in tgt_meta.iterrows()
            if _is_numeric_type(row["DATA_TYPE"]) and row["COLUMN_NAME"].upper() not in ignore_upper
        }

        common_numeric = sorted(src_numeric & tgt_numeric)
        if not common_numeric:
            return [], []

        # Get cardinality from source to classify columns
        cardinality = _get_cardinality(src_conn, config.source_table, common_numeric, config.where)

        measures = []
        identifiers = []
        for col in common_numeric:
            ratio = cardinality.get(col, 0.0)
            if ratio > _ID_CARDINALITY_THRESHOLD:
                identifiers.append(col)
                logger.info("Column %s classified as IDENTIFIER (cardinality %.1f%%)", col, ratio * 100)
            else:
                measures.append(col)
                logger.info("Column %s classified as MEASURE (cardinality %.1f%%)", col, ratio * 100)

        logger.info("Auto-detected %d measures %s, %d identifiers %s",
                     len(measures), measures, len(identifiers), identifiers)
        return measures, identifiers

    def run(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:
        logger.info("Running aggregate check: %s → %s", config.source_table, config.target_table)

        agg_columns = config.columns if config.columns and config.columns != ["NA"] else []
        id_columns = config.extra.get("id_columns", [])
        if id_columns == ["NA"]:
            id_columns = []
        functions = config.functions

        # Resolve group-by columns: join_keys from UI, or extra.group_by from config
        group_by_cols: list[str] = []
        join_keys = config.join_keys if config.join_keys and config.join_keys != ["NA"] else []
        if join_keys:
            group_by_cols = [k.upper() for k in join_keys]
        else:
            gb = config.extra.get("group_by", "")
            if gb:
                group_by_cols = [gb.upper()]

        # Per-column tolerance: dict mapping "FUNC_COL" → threshold, or global default
        col_tolerances = config.extra.get("tolerances", {})
        default_tolerance = config.extra.get("tolerance", 0.001)

        # ── Auto-detect and classify numeric columns ──────────────────────
        auto_detected = False
        if not agg_columns:
            measures, detected_ids = self._detect_and_classify_columns(src_conn, tgt_conn, config)
            agg_columns = measures
            # Auto-populate id_columns from high-cardinality numerics (if not manually set)
            if not id_columns:
                id_columns = detected_ids
            auto_detected = True

        # Exclude group-by columns from aggregation (they're keys, not measures)
        if group_by_cols:
            gb_set = set(group_by_cols)
            agg_columns = [c for c in agg_columns if c.upper() not in gb_set]
            id_columns = [c for c in id_columns if c.upper() not in gb_set]

        if not agg_columns and not id_columns:
            return CheckResult(
                check_type=self.name,
                status=Status.PASS,
                message="No numeric columns found to aggregate",
            )

        mismatches: list[dict] = []
        warnings: list[dict] = []

        # ── 1. Global aggregate comparison (always) ───────────────────────
        if agg_columns:
            src_agg = src_conn.get_aggregates(
                config.source_table, agg_columns, functions, config.where
            )
            tgt_agg = tgt_conn.get_aggregates(
                config.target_table, agg_columns, functions, config.where
            )
            src_agg.columns = [c.upper() for c in src_agg.columns]
            tgt_agg.columns = [c.upper() for c in tgt_agg.columns]

            for col in src_agg.columns:
                if col not in tgt_agg.columns:
                    continue
                try:
                    s_val = float(src_agg[col].iloc[0])
                    t_val = float(tgt_agg[col].iloc[0])
                except (ValueError, TypeError):
                    continue

                tol = col_tolerances.get(col, default_tolerance)
                diff = s_val - t_val

                if s_val != 0:
                    pct_diff = round((diff / s_val * 100), 4)
                elif t_val != 0:
                    pct_diff = float("inf")
                else:
                    pct_diff = 0.0

                # Check tolerance: if tolerance < 1, treat as percentage; else absolute
                if isinstance(tol, float) and 0 < tol < 1:
                    exceeds = abs(pct_diff) > tol * 100 if not math.isinf(pct_diff) else True
                    near_threshold = abs(pct_diff) > tol * 50 if not math.isinf(pct_diff) else False
                else:
                    exceeds = abs(diff) > float(tol)
                    near_threshold = abs(diff) > float(tol) * 0.5

                row = {
                    "METRIC": col,
                    "SRC_VALUE": s_val,
                    "TGT_VALUE": t_val,
                    "DIFF": round(diff, 5),
                    "PCT_DIFF": round(pct_diff, 4) if not math.isinf(pct_diff) else "Inf",
                    "TOLERANCE": tol,
                }

                if exceeds:
                    mismatches.append(row)
                elif near_threshold and abs(diff) > 0:
                    warnings.append(row)

        # ── 2. GROUP BY aggregate comparison (when join_keys provided) ────
        if agg_columns and group_by_cols:
            gb_result = self._group_by_aggregates(
                src_conn, tgt_conn, config, agg_columns, functions,
                group_by_cols, col_tolerances, default_tolerance
            )
            mismatches.extend(gb_result["mismatches"])
            warnings.extend(gb_result["warnings"])

        # ── 3. ID boundary check (MIN/MAX) ───────────────────────────────
        if id_columns:
            src_id = src_conn.get_aggregates(
                config.source_table, id_columns, ["MIN", "MAX"], config.where
            )
            tgt_id = tgt_conn.get_aggregates(
                config.target_table, id_columns, ["MIN", "MAX"], config.where
            )
            src_id.columns = [c.upper() for c in src_id.columns]
            tgt_id.columns = [c.upper() for c in tgt_id.columns]

            for col in src_id.columns:
                if col not in tgt_id.columns:
                    continue
                s_val = src_id[col].iloc[0]
                t_val = tgt_id[col].iloc[0]
                if str(s_val) != str(t_val):
                    mismatches.append({
                        "METRIC": col,
                        "SRC_VALUE": s_val,
                        "TGT_VALUE": t_val,
                        "DIFF": "",
                        "PCT_DIFF": "N/A (boundary)",
                        "TOLERANCE": "exact",
                    })

        # ── Status ────────────────────────────────────────────────────────
        if mismatches:
            status = Status.FAIL
        elif warnings:
            status = Status.WARNING
        else:
            status = Status.PASS

        all_issues = mismatches + warnings
        details = pd.DataFrame(all_issues) if all_issues else None

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={
                "measure_columns": ", ".join(agg_columns) if agg_columns else "none",
                "id_columns": ", ".join(id_columns) if id_columns else "none",
                "auto_detected": auto_detected,
                "agg_mismatches": len(mismatches),
                "agg_warnings": len(warnings),
                "group_by": ", ".join(group_by_cols) if group_by_cols else "none",
            },
            details=details,
            message=(
                f"{'Auto-detected' if auto_detected else 'Checked'} "
                f"{len(agg_columns)} measure(s), {len(id_columns)} identifier(s): "
                f"{len(mismatches)} mismatch(es), {len(warnings)} warning(s)"
            ),
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _group_by_aggregates(
        src_conn, tgt_conn, config: CheckConfig,
        agg_columns: list[str], functions: list[str],
        group_by_cols: list[str], col_tolerances: dict, default_tolerance: float,
    ) -> dict:
        """Compare aggregates broken down by one or more grouping columns."""
        mismatches: list[dict] = []
        warnings: list[dict] = []

        src_df = AggregateCheck._group_by_single(src_conn, config.source_table, agg_columns, functions, group_by_cols, config.where)
        tgt_df = AggregateCheck._group_by_single(tgt_conn, config.target_table, agg_columns, functions, group_by_cols, config.where)

        gb_upper = [c.upper() for c in group_by_cols]
        merged = src_df.merge(tgt_df, on=gb_upper, how="outer", suffixes=("_SRC", "_TGT"))

        agg_cols_in_merge = [c for c in merged.columns if c.endswith("_SRC")]
        for src_col_name in agg_cols_in_merge:
            base = src_col_name[:-4]  # Remove _SRC
            tgt_col_name = f"{base}_TGT"
            if tgt_col_name not in merged.columns:
                continue

            tol = col_tolerances.get(base, default_tolerance)

            for _, row in merged.iterrows():
                try:
                    s_val = float(row[src_col_name]) if pd.notna(row[src_col_name]) else 0.0
                    t_val = float(row[tgt_col_name]) if pd.notna(row[tgt_col_name]) else 0.0
                except (ValueError, TypeError):
                    continue

                diff = s_val - t_val
                if s_val != 0:
                    pct_diff = round((diff / s_val * 100), 4)
                elif t_val != 0:
                    pct_diff = float("inf")
                else:
                    continue  # Both zero — skip

                if isinstance(tol, float) and 0 < tol < 1:
                    exceeds = abs(pct_diff) > tol * 100 if not math.isinf(pct_diff) else True
                else:
                    exceeds = abs(diff) > float(tol)

                if exceeds:
                    # Build key label: [REGION=East, CATEGORY=Electronics]
                    key_parts = [f"{k}={row[k]}" for k in gb_upper]
                    key_label = ", ".join(key_parts)
                    mismatches.append({
                        "METRIC": f"{base} [{key_label}]",
                        "SRC_VALUE": s_val,
                        "TGT_VALUE": t_val,
                        "DIFF": round(diff, 5),
                        "PCT_DIFF": round(pct_diff, 4) if not math.isinf(pct_diff) else "Inf",
                        "TOLERANCE": tol,
                    })

        return {"mismatches": mismatches, "warnings": warnings}

    @staticmethod
    def _group_by_single(conn, table: str, agg_columns: list[str],
                          functions: list[str], group_by_cols: list[str],
                          where: str = "") -> pd.DataFrame:
        """Get grouped aggregates from a single connection (SQL or CSV)."""
        try:
            gb_safe = [quote_identifier(safe_identifier(c)) for c in group_by_cols]
            gb_list = ", ".join(gb_safe)
            cols_safe = safe_identifiers(agg_columns)
            tbl = safe_table_expr(table)
            clause = f"WHERE {where}" if where else ""

            expressions = list(gb_safe)
            for col in cols_safe:
                for func in functions:
                    expressions.append(
                        f'COALESCE(CAST({func}("{col}") AS DECIMAL(38,5)), 0) AS "{func}_{col}"'
                    )
            query = f"SELECT {', '.join(expressions)} FROM {tbl} {clause} GROUP BY {gb_list}"
            df = conn.execute_query(query)
            df.columns = [c.upper() for c in df.columns]
            return df
        except (NotImplementedError, Exception):
            # Fallback: pandas-based groupby for CSV connectors
            raw = conn.read_dataframe()
            gb_matches = []
            for gb_col in group_by_cols:
                match = [c for c in raw.columns if c.upper() == gb_col.upper()]
                if not match:
                    raise ValueError(f"Column {gb_col} not found")
                gb_matches.append(match[0])

            func_map = {"MIN": "min", "MAX": "max", "AVG": "mean", "SUM": "sum"}
            result_rows = []
            for grp_vals, grp_df in raw.groupby(gb_matches):
                # grp_vals is a tuple when multiple columns, scalar when single
                if not isinstance(grp_vals, tuple):
                    grp_vals = (grp_vals,)
                row = {gb_col.upper(): val for gb_col, val in zip(group_by_cols, grp_vals)}
                for col in agg_columns:
                    col_match = [c for c in grp_df.columns if c.upper() == col.upper()]
                    if not col_match:
                        continue
                    series = pd.to_numeric(grp_df[col_match[0]], errors="coerce")
                    for func in functions:
                        val = getattr(series, func_map.get(func, "sum"))()
                        row[f"{func}_{col.upper()}"] = round(val, 5) if pd.notna(val) else 0
                result_rows.append(row)
            return pd.DataFrame(result_rows)
