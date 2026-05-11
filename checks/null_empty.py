"""Null count comparison check."""

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

        # Align columns
        src_nulls.columns = [c.upper() for c in src_nulls.columns]
        tgt_nulls.columns = [c.upper() for c in tgt_nulls.columns]

        mismatched = []
        for col in src_nulls.columns:
            if col in tgt_nulls.columns:
                s = int(src_nulls[col].iloc[0])
                t = int(tgt_nulls[col].iloc[0])
                if s != t:
                    diff = s - t
                    src_pct = round((s / src_row_count * 100), 2) if src_row_count else 0.0
                    tgt_pct = round((t / tgt_row_count * 100), 2) if tgt_row_count else 0.0
                    mismatched.append({
                        "COLUMN": col,
                        "SRC_NULLS": s,
                        "TGT_NULLS": t,
                        "DIFF": diff,
                        "SRC_NULL_PCT": src_pct,
                        "TGT_NULL_PCT": tgt_pct,
                    })

        details = pd.DataFrame(mismatched) if mismatched else None
        status = Status.FAIL if mismatched else Status.PASS

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={"mismatched_null_columns": len(mismatched)},
            details=details,
            message=f"{len(mismatched)} column(s) with null-count mismatch",
        )
