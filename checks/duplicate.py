"""Duplicate-record check."""

import logging

import pandas as pd

from .base import BaseCheck, CheckConfig, CheckResult, Status

logger = logging.getLogger(__name__)


class DuplicateCheck(BaseCheck):
    name = "duplicate"

    def run(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:
        logger.info("Running duplicate check: %s → %s", config.source_table, config.target_table)

        columns = config.columns
        if not columns or columns == ["NA"]:
            columns = tgt_conn.get_column_names(
                config.target_table, exclude=config.ignore_columns
            )

        src_dupes = src_conn.get_duplicates(config.source_table, columns, config.where)
        tgt_dupes = tgt_conn.get_duplicates(config.target_table, columns, config.where)

        src_dupes.columns = [c.upper() for c in src_dupes.columns]
        tgt_dupes.columns = [c.upper() for c in tgt_dupes.columns]

        # Align dtypes
        try:
            tgt_dupes = tgt_dupes.astype(src_dupes.dtypes)
        except (ValueError, TypeError):
            pass

        # Find exclusive duplicates on each side
        merged = src_dupes.merge(tgt_dupes, how="outer", indicator=True)
        only_src = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])
        only_tgt = merged[merged["_merge"] == "right_only"].drop(columns=["_merge"])

        has_diff = len(only_src) > 0 or len(only_tgt) > 0
        status = Status.FAIL if has_diff else Status.PASS

        details_parts = []
        if len(only_src) > 0:
            only_src["_side"] = "source_only"
            details_parts.append(only_src)
        if len(only_tgt) > 0:
            only_tgt["_side"] = "target_only"
            details_parts.append(only_tgt)
        details = pd.concat(details_parts, ignore_index=True) if details_parts else None

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={
                "src_duplicate_groups": len(src_dupes),
                "tgt_duplicate_groups": len(tgt_dupes),
                "only_in_source": len(only_src),
                "only_in_target": len(only_tgt),
            },
            details=details,
            message=(
                f"Src dupe groups={len(src_dupes)}, Tgt dupe groups={len(tgt_dupes)}, "
                f"Only-in-src={len(only_src)}, Only-in-tgt={len(only_tgt)}"
            ),
        )
