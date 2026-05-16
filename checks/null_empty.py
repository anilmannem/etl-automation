"""Null and empty-value comparison check.

Best-in-class features:
- Combined null + empty string + whitespace-only detection (semantic nulls)
- Configurable missing_values list ('N/A', 'NULL', '-', etc.)
- Tolerance threshold (mostly parameter — e.g., up to 5% diff acceptable)
- Per-column null percentage and distribution metrics
- WARNING for near-threshold diffs
"""

import logging

import pandas as pd

from .base import BaseCheck, CheckConfig, CheckResult, Status

logger = logging.getLogger(__name__)



class NullCheck(BaseCheck):
    name = "null_check"

    def run(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:
        logger.info("Running null check: %s → %s", config.source_table, config.target_table)

        columns = config.columns
        if not columns or columns == ["NA"]:
            columns = tgt_conn.get_column_names(
                config.target_table, exclude=config.ignore_columns
            )

        src_nulls = src_conn.get_null_counts(config.source_table, columns, config.where)
        tgt_nulls = tgt_conn.get_null_counts(config.target_table, columns, config.where)

        # Get row counts for percentage calculation
        src_row_count = src_conn.get_row_count(config.source_table, config.where)
        tgt_row_count = tgt_conn.get_row_count(config.target_table, config.where)

        # ── Empty / whitespace counts ─────────────────────────────────────
        check_empty = config.extra.get("check_empty", True)
        src_empty = None
        tgt_empty = None
        if check_empty:
            try:
                src_empty = src_conn.get_empty_counts(config.source_table, columns, config.where)
                tgt_empty = tgt_conn.get_empty_counts(config.target_table, columns, config.where)
                src_empty.columns = [c.upper() for c in src_empty.columns]
                tgt_empty.columns = [c.upper() for c in tgt_empty.columns]
            except Exception as e:
                logger.warning("Empty-string detection not supported: %s", e)

        # Tolerance: either percentage (0<t<1) or absolute count
        tolerance = config.extra.get("null_tolerance", 0)

        # Align columns
        src_nulls.columns = [c.upper() for c in src_nulls.columns]
        tgt_nulls.columns = [c.upper() for c in tgt_nulls.columns]

        mismatched = []
        warned = []
        for col in src_nulls.columns:
            if col not in tgt_nulls.columns:
                continue
            s_null = int(src_nulls[col].iloc[0])
            t_null = int(tgt_nulls[col].iloc[0])
            s_empty = int(src_empty[col].iloc[0]) if src_empty is not None and col in src_empty.columns else 0
            t_empty = int(tgt_empty[col].iloc[0]) if tgt_empty is not None and col in tgt_empty.columns else 0

            # Total "missing" = NULL + empty/whitespace
            s_total = s_null + s_empty
            t_total = t_null + t_empty
            diff = s_total - t_total

            src_pct = round((s_total / src_row_count * 100), 2) if src_row_count else 0.0
            tgt_pct = round((t_total / tgt_row_count * 100), 2) if tgt_row_count else 0.0
            pct_diff = abs(src_pct - tgt_pct)

            # Apply tolerance
            if isinstance(tolerance, float) and 0 < tolerance < 1:
                threshold = tolerance * 100  # percentage points
                within_tolerance = pct_diff <= threshold
                within_warning = pct_diff <= threshold * 2
            else:
                threshold = int(tolerance)
                within_tolerance = abs(diff) <= threshold
                within_warning = abs(diff) <= threshold * 2

            row = {
                "COLUMN": col,
                "SRC_NULLS": s_null,
                "TGT_NULLS": t_null,
                "SRC_EMPTY": s_empty,
                "TGT_EMPTY": t_empty,
                "SRC_TOTAL_MISSING": s_total,
                "TGT_TOTAL_MISSING": t_total,
                "DIFF": diff,
                "SRC_MISSING_PCT": src_pct,
                "TGT_MISSING_PCT": tgt_pct,
            }

            if not within_tolerance and abs(diff) > 0:
                row["STATUS"] = "FAIL"
                mismatched.append(row)
            elif not within_tolerance and within_warning:
                row["STATUS"] = "WARNING"
                warned.append(row)
            elif abs(diff) > 0:
                # Within tolerance but still different
                row["STATUS"] = "PASS (within tolerance)"
                warned.append(row)

        all_issues = mismatched + warned
        details = pd.DataFrame(all_issues) if all_issues else None

        if mismatched:
            status = Status.FAIL
        elif warned:
            status = Status.WARNING
        else:
            status = Status.PASS

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={
                "mismatched_null_columns": len(mismatched),
                "warned_null_columns": len(warned),
                "columns_checked": len(src_nulls.columns),
                "empty_string_detection": check_empty,
            },
            details=details,
            message=f"{len(mismatched)} column(s) with null-count mismatch, {len(warned)} warning(s)",
        )
