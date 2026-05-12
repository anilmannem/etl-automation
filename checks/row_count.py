"""Row-count comparison check.

Best-in-class features:
- Partition-level row count breakdown (GROUP BY a partition column)
- Tolerance supports both absolute and percentage thresholds
- WARNING status when diff is within 2× tolerance (early warning)
- Freshness check via max timestamp column
- Sample diff rows on mismatch using EXCEPT
"""

import logging

import pandas as pd

from .base import BaseCheck, CheckConfig, CheckResult, Status
from ..connectors.base import safe_identifier, safe_identifiers, quote_identifier

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
            threshold = int(src_count * tolerance)
        else:
            threshold = int(tolerance)

        if abs(diff) <= threshold:
            status = Status.PASS
        elif abs(diff) <= threshold * 2 and threshold > 0:
            status = Status.WARNING
        else:
            status = Status.FAIL

        metrics = {
            "src_row_count": src_count,
            "tgt_row_count": tgt_count,
            "row_count_diff": diff,
            "pct_diff": pct_diff,
        }

        details_parts: list[pd.DataFrame] = []

        # ── Partition-level breakdown ─────────────────────────────────────
        partition_col = config.extra.get("partition_column", "")
        if partition_col:
            part_df = self._partition_counts(src_conn, tgt_conn, config, partition_col)
            if part_df is not None:
                mismatch_parts = part_df[part_df["SRC_COUNT"] != part_df["TGT_COUNT"]]
                metrics["partition_mismatches"] = len(mismatch_parts)
                metrics["partitions_checked"] = len(part_df)
                if len(mismatch_parts) > 0:
                    details_parts.append(mismatch_parts)
                    if status == Status.PASS:
                        status = Status.WARNING

        # ── Freshness check ───────────────────────────────────────────────
        freshness_col = config.extra.get("freshness_column", "")
        if freshness_col:
            try:
                src_max = src_conn.get_max_timestamp(config.source_table, freshness_col, config.where)
                tgt_max = tgt_conn.get_max_timestamp(config.target_table, freshness_col, config.where)
                metrics["src_max_timestamp"] = str(src_max)
                metrics["tgt_max_timestamp"] = str(tgt_max)
                if str(src_max) != str(tgt_max):
                    metrics["freshness_match"] = False
                    if status == Status.PASS:
                        status = Status.WARNING
                else:
                    metrics["freshness_match"] = True
            except Exception as e:
                logger.warning("Freshness check failed: %s", e)

        # ── Sample diff rows (on mismatch) ───────────────────────────────
        if status != Status.PASS and config.join_keys and config.join_keys != ["NA"]:
            sample = self._get_sample_diff_rows(src_conn, tgt_conn, config, max_sample=20)
            if sample is not None:
                details_parts.append(sample)

        details = pd.concat(details_parts, ignore_index=True) if details_parts else None

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics=metrics,
            details=details,
            message=f"Source={src_count:,}, Target={tgt_count:,}, Diff={diff:,} ({pct_diff}%)",
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _partition_counts(src_conn, tgt_conn, config: CheckConfig,
                          partition_col: str) -> pd.DataFrame | None:
        """Get row counts grouped by partition column from both sides."""
        try:
            # Try pandas-based path first (works for CSV + SQL connectors)
            src_df = RowCountCheck._partition_count_single(src_conn, config.source_table, partition_col, config.where)
            tgt_df = RowCountCheck._partition_count_single(tgt_conn, config.target_table, partition_col, config.where)

            merged = src_df.merge(
                tgt_df, on="PARTITION_VAL", how="outer", suffixes=("_SRC", "_TGT")
            ).rename(columns={"CNT_SRC": "SRC_COUNT", "CNT_TGT": "TGT_COUNT"})
            merged["SRC_COUNT"] = merged["SRC_COUNT"].fillna(0).astype(int)
            merged["TGT_COUNT"] = merged["TGT_COUNT"].fillna(0).astype(int)
            merged["DIFF"] = merged["SRC_COUNT"] - merged["TGT_COUNT"]
            return merged.sort_values("PARTITION_VAL").reset_index(drop=True)
        except Exception as e:
            logger.warning("Partition count failed: %s", e)
            return None

    @staticmethod
    def _partition_count_single(conn, table: str, partition_col: str, where: str = "") -> pd.DataFrame:
        """Get partition counts from a single connection (SQL or CSV)."""
        try:
            col = quote_identifier(safe_identifier(partition_col))
            tbl = safe_identifier(table)
            clause = f"WHERE {where}" if where else ""
            df = conn.execute_query(
                f"SELECT {col} AS PARTITION_VAL, COUNT(*) AS CNT FROM {tbl} {clause} GROUP BY {col}"
            )
            df.columns = [c.upper() for c in df.columns]
            return df
        except (NotImplementedError, Exception):
            # Fallback: pandas-based groupby for CSV connectors
            raw = conn.read_dataframe()
            pcol_match = [c for c in raw.columns if c.upper() == partition_col.upper()]
            if not pcol_match:
                raise ValueError(f"Column {partition_col} not found")
            counts = raw.groupby(pcol_match[0]).size().reset_index(name="CNT")
            counts.columns = ["PARTITION_VAL", "CNT"]
            return counts

    @staticmethod
    def _get_sample_diff_rows(src_conn, tgt_conn, config: CheckConfig,
                              max_sample: int = 20) -> pd.DataFrame | None:
        """Fetch sample rows that exist only on one side using EXCEPT."""
        try:
            keys = safe_identifiers(config.join_keys)
            key_cols = ", ".join(f'"{k}"' for k in keys)
            src_table = safe_identifier(config.source_table)
            tgt_table = safe_identifier(config.target_table)
            clause = f"WHERE {config.where}" if config.where else ""

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
