"""Row-count comparison check."""

import logging

import pandas as pd

from .base import BaseCheck, CheckConfig, CheckResult, Status
from ..connectors.base import safe_identifier, safe_identifiers

logger = logging.getLogger(__name__)


class RowCountCheck(BaseCheck):
    name = "row_count"

    def run(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:
        logger.info("Running row-count check: %s → %s", config.source_table, config.target_table)

        src_count = src_conn.get_row_count(config.source_table, config.where)
        tgt_count = tgt_conn.get_row_count(config.target_table, config.where)
        diff = src_count - tgt_count
        pct_diff = round((diff / src_count * 100), 4) if src_count else 0.0

        tolerance = config.tolerance
        if isinstance(tolerance, float) and 0 < tolerance < 1:
            # percentage tolerance
            threshold = int(src_count * tolerance)
        else:
            threshold = int(tolerance)

        status = Status.PASS if abs(diff) <= threshold else Status.FAIL

        # On mismatch: fetch sample rows unique to each side (if join keys available)
        details = None
        if status == Status.FAIL and config.join_keys and config.join_keys != ["NA"]:
            details = self._get_sample_diff_rows(
                src_conn, tgt_conn, config, max_sample=20
            )

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={
                "src_row_count": src_count,
                "tgt_row_count": tgt_count,
                "row_count_diff": diff,
                "pct_diff": pct_diff,
            },
            details=details,
            message=f"Source={src_count:,}, Target={tgt_count:,}, Diff={diff:,} ({pct_diff}%)",
        )

    @staticmethod
    def _get_sample_diff_rows(src_conn, tgt_conn, config: CheckConfig,
                              max_sample: int = 20) -> pd.DataFrame | None:
        """Fetch sample rows that exist only on one side using EXCEPT/MINUS."""
        try:
            keys = safe_identifiers(config.join_keys)
            key_cols = ", ".join(f'"{k}"' for k in keys)
            src_table = safe_identifier(config.source_table)
            tgt_table = safe_identifier(config.target_table)
            clause = f"WHERE {config.where}" if config.where else ""

            # Rows in source but not in target
            only_src_q = (
                f"SELECT {key_cols} FROM {src_table} {clause} "
                f"EXCEPT "
                f"SELECT {key_cols} FROM {tgt_table} {clause}"
            )
            only_src = src_conn.execute_query(
                f"SELECT * FROM ({only_src_q}) t SAMPLE {max_sample}"
            )
            only_src.columns = [c.upper() for c in only_src.columns]
            only_src["_side"] = "only_in_source"

            # Rows in target but not in source
            only_tgt_q = (
                f"SELECT {key_cols} FROM {tgt_table} {clause} "
                f"EXCEPT "
                f"SELECT {key_cols} FROM {src_table} {clause}"
            )
            only_tgt = tgt_conn.execute_query(
                f"SELECT * FROM ({only_tgt_q}) t SAMPLE {max_sample}"
            )
            only_tgt.columns = [c.upper() for c in only_tgt.columns]
            only_tgt["_side"] = "only_in_target"

            parts = [df for df in [only_src, only_tgt] if len(df) > 0]
            return pd.concat(parts, ignore_index=True) if parts else None
        except Exception as e:
            logger.warning("Could not fetch sample diff rows: %s", e)
            return None
