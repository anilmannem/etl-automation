"""Metadata (schema) comparison check."""

import logging

import pandas as pd

from .base import BaseCheck, CheckConfig, CheckResult, Status

logger = logging.getLogger(__name__)


class MetadataCheck(BaseCheck):
    name = "metadata"

    def run(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:
        logger.info("Running metadata check: %s → %s", config.source_table, config.target_table)

        src_meta = src_conn.get_metadata(config.source_table)
        tgt_meta = tgt_conn.get_metadata(config.target_table)

        # Filter out ignored columns
        ignore_upper = {c.upper() for c in config.ignore_columns}
        src_meta = src_meta[~src_meta["COLUMN_NAME"].str.upper().isin(ignore_upper)].reset_index(drop=True)
        tgt_meta = tgt_meta[~tgt_meta["COLUMN_NAME"].str.upper().isin(ignore_upper)].reset_index(drop=True)

        src_cols = set(src_meta["COLUMN_NAME"].str.upper())
        tgt_cols = set(tgt_meta["COLUMN_NAME"].str.upper())

        only_in_src = sorted(src_cols - tgt_cols)
        only_in_tgt = sorted(tgt_cols - src_cols)
        common_cols = sorted(src_cols & tgt_cols)

        # Build a detailed comparison on common columns
        mismatches = []
        if common_cols:
            src_lookup = src_meta.set_index(src_meta["COLUMN_NAME"].str.upper())
            tgt_lookup = tgt_meta.set_index(tgt_meta["COLUMN_NAME"].str.upper())
            for col in common_cols:
                src_row = src_lookup.loc[col]
                tgt_row = tgt_lookup.loc[col]
                dtype_match = str(src_row["DATA_TYPE"]).strip().upper() == str(tgt_row["DATA_TYPE"]).strip().upper()
                null_match = str(src_row["NULLABLE"]).strip().upper() == str(tgt_row["NULLABLE"]).strip().upper()
                if not dtype_match or not null_match:
                    mismatches.append({
                        "COLUMN": col,
                        "SRC_DATA_TYPE": src_row["DATA_TYPE"],
                        "TGT_DATA_TYPE": tgt_row["DATA_TYPE"],
                        "DATA_TYPE_MATCH": dtype_match,
                        "SRC_NULLABLE": src_row["NULLABLE"],
                        "TGT_NULLABLE": tgt_row["NULLABLE"],
                        "NULLABLE_MATCH": null_match,
                    })

        details_df = pd.DataFrame(mismatches) if mismatches else None
        has_issues = bool(only_in_src or only_in_tgt or mismatches)
        status = Status.FAIL if has_issues else Status.PASS

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={
                "src_column_count": len(src_cols),
                "tgt_column_count": len(tgt_cols),
                "columns_only_in_source": ", ".join(only_in_src) if only_in_src else "",
                "columns_only_in_target": ", ".join(only_in_tgt) if only_in_tgt else "",
                "mismatched_columns": len(mismatches),
            },
            details=details_df,
            message=(
                f"Src cols={len(src_cols)}, Tgt cols={len(tgt_cols)}, "
                f"Only in src={len(only_in_src)}, Only in tgt={len(only_in_tgt)}, "
                f"Type/null mismatches={len(mismatches)}"
            ),
        )
