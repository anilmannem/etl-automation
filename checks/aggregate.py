"""Aggregate comparison check (MIN/MAX/AVG/SUM + ID boundary checks)."""

import logging

import pandas as pd

from .base import BaseCheck, CheckConfig, CheckResult, Status

logger = logging.getLogger(__name__)


class AggregateCheck(BaseCheck):
    name = "aggregate"

    def run(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:
        logger.info("Running aggregate check: %s → %s", config.source_table, config.target_table)

        agg_columns = config.columns if config.columns and config.columns != ["NA"] else []
        id_columns = config.extra.get("id_columns", [])
        if id_columns == ["NA"]:
            id_columns = []
        functions = config.functions

        if not agg_columns and not id_columns:
            return CheckResult(
                check_type=self.name,
                status=Status.NOT_APPLICABLE,
                message="No aggregate or ID columns specified",
            )

        mismatches = []
        details_frames = []

        # Numeric aggregate check
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
                if col in tgt_agg.columns:
                    s_val = float(src_agg[col].iloc[0])
                    t_val = float(tgt_agg[col].iloc[0])
                    if abs(s_val - t_val) > 0.001:
                        diff = s_val - t_val
                        pct_diff = round((diff / s_val * 100), 4) if s_val != 0 else (
                            999999.99 if t_val != 0 else 0.0
                        )
                        mismatches.append({
                            "METRIC": col,
                            "SRC_VALUE": s_val,
                            "TGT_VALUE": t_val,
                            "DIFF": diff,
                            "PCT_DIFF": pct_diff,
                        })

        # ID boundary check (MIN/MAX only)
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
                if col in tgt_id.columns:
                    s_val = src_id[col].iloc[0]
                    t_val = tgt_id[col].iloc[0]
                    if str(s_val) != str(t_val):
                        mismatches.append({
                            "METRIC": col,
                            "SRC_VALUE": s_val,
                            "TGT_VALUE": t_val,
                            "DIFF": "",
                            "PCT_DIFF": "N/A",
                        })

        status = Status.PASS if not mismatches else Status.FAIL
        details = pd.DataFrame(mismatches) if mismatches else None

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={"agg_mismatches": len(mismatches)},
            details=details,
            message=f"{len(mismatches)} aggregate metric(s) mismatched",
        )
