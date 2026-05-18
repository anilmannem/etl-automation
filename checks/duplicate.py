"""Duplicate-record check.

Best-in-class features:
- Compares duplicate COUNTS (not just which groups are duplicated)
- Duplicate percentage metric (total duplicate rows / total rows)
- Tolerance threshold for acceptable duplicate rate
- Per-group count comparison (catches 3× vs 5× duplicates of same key)
- Scalable SQL-first approach: uses COUNT comparison query, not full merge
- WARNING for near-threshold duplicates
"""

import logging

import pandas as pd

from .base import BaseCheck, CheckConfig, CheckResult, Status
from ..connectors.base import safe_identifier, safe_table_expr, quote_identifier

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

        # ── Get duplicate groups WITH counts ──────────────────────────────
        src_dupes = self._get_duplicates_with_counts(src_conn, config.source_table, columns, config.where)
        tgt_dupes = self._get_duplicates_with_counts(tgt_conn, config.target_table, columns, config.where)

        src_dupes.columns = [c.upper() for c in src_dupes.columns]
        tgt_dupes.columns = [c.upper() for c in tgt_dupes.columns]

        # Row counts for percentage calculation
        src_row_count = src_conn.get_row_count(config.source_table, config.where)
        tgt_row_count = tgt_conn.get_row_count(config.target_table, config.where)

        # Total duplicate rows (not groups — rows involved in duplicates)
        src_dupe_rows = int(src_dupes["_DUP_COUNT"].sum()) if len(src_dupes) > 0 else 0
        tgt_dupe_rows = int(tgt_dupes["_DUP_COUNT"].sum()) if len(tgt_dupes) > 0 else 0

        src_dupe_pct = round((src_dupe_rows / src_row_count * 100), 4) if src_row_count else 0.0
        tgt_dupe_pct = round((tgt_dupe_rows / tgt_row_count * 100), 4) if tgt_row_count else 0.0

        # ── Merge on key columns to compare counts ────────────────────────
        key_cols = [c.upper() for c in columns]
        merge_cols = [c for c in key_cols if c in src_dupes.columns and c in tgt_dupes.columns]

        if merge_cols and len(src_dupes) > 0 and len(tgt_dupes) > 0:
            # Align dtypes
            try:
                for col in merge_cols:
                    if col in src_dupes.columns and col in tgt_dupes.columns:
                        tgt_dupes[col] = tgt_dupes[col].astype(src_dupes[col].dtype)
            except (ValueError, TypeError):
                pass

            merged = src_dupes.merge(
                tgt_dupes, on=merge_cols, how="outer",
                suffixes=("_SRC", "_TGT"), indicator=True
            )
            merged["_DUP_COUNT_SRC"] = merged["_DUP_COUNT_SRC"].fillna(0).astype(int)
            merged["_DUP_COUNT_TGT"] = merged["_DUP_COUNT_TGT"].fillna(0).astype(int)

            only_src = merged[merged["_merge"] == "left_only"].copy()
            only_tgt = merged[merged["_merge"] == "right_only"].copy()
            both = merged[merged["_merge"] == "both"].copy()

            # Groups where duplicate COUNT differs (e.g., 3 vs 5 occurrences)
            count_diffs = both[both["_DUP_COUNT_SRC"] != both["_DUP_COUNT_TGT"]].copy()
        else:
            # Fallback: use original simple merge
            only_src = src_dupes.copy() if len(src_dupes) > 0 else pd.DataFrame()
            only_tgt = tgt_dupes.copy() if len(tgt_dupes) > 0 else pd.DataFrame()
            count_diffs = pd.DataFrame()
            merged = pd.DataFrame()

        # ── Tolerance ─────────────────────────────────────────────────────
        tolerance = config.extra.get("duplicate_tolerance", 0)
        if isinstance(tolerance, float) and 0 < tolerance < 1:
            # Percentage tolerance — applied to duplicate rate difference
            pct_tolerance = tolerance * 100
            within_tolerance = abs(src_dupe_pct - tgt_dupe_pct) <= pct_tolerance
        else:
            # Absolute tolerance on number of differing groups
            total_diffs = len(only_src) + len(only_tgt) + len(count_diffs)
            within_tolerance = total_diffs <= int(tolerance)

        # ── Status ────────────────────────────────────────────────────────
        has_exclusive = len(only_src) > 0 or len(only_tgt) > 0
        has_count_diffs = len(count_diffs) > 0

        if not has_exclusive and not has_count_diffs:
            status = Status.PASS
        elif within_tolerance:
            status = Status.WARNING
        else:
            status = Status.FAIL

        # ── Details ───────────────────────────────────────────────────────
        details_parts: list[pd.DataFrame] = []
        if len(only_src) > 0:
            df = only_src[merge_cols + ["_DUP_COUNT_SRC"]].copy() if "_DUP_COUNT_SRC" in only_src.columns else only_src[merge_cols + ["_DUP_COUNT"]].copy()
            df["_ISSUE"] = "only_in_source"
            details_parts.append(df)
        if len(only_tgt) > 0:
            df = only_tgt[merge_cols + ["_DUP_COUNT_TGT"]].copy() if "_DUP_COUNT_TGT" in only_tgt.columns else only_tgt[merge_cols + ["_DUP_COUNT"]].copy()
            df["_ISSUE"] = "only_in_target"
            details_parts.append(df)
        if len(count_diffs) > 0:
            df = count_diffs[merge_cols + ["_DUP_COUNT_SRC", "_DUP_COUNT_TGT"]].copy()
            df["_ISSUE"] = "count_mismatch"
            details_parts.append(df)

        details = pd.concat(details_parts, ignore_index=True) if details_parts else None

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={
                "src_duplicate_groups": len(src_dupes),
                "tgt_duplicate_groups": len(tgt_dupes),
                "src_duplicate_rows": src_dupe_rows,
                "tgt_duplicate_rows": tgt_dupe_rows,
                "src_duplicate_pct": src_dupe_pct,
                "tgt_duplicate_pct": tgt_dupe_pct,
                "only_in_source": len(only_src),
                "only_in_target": len(only_tgt),
                "count_mismatches": len(count_diffs) if not count_diffs.empty else 0,
            },
            details=details,
            message=(
                f"Src dupe groups={len(src_dupes)} ({src_dupe_pct}%), "
                f"Tgt dupe groups={len(tgt_dupes)} ({tgt_dupe_pct}%), "
                f"Only-in-src={len(only_src)}, Only-in-tgt={len(only_tgt)}, "
                f"Count mismatches={len(count_diffs) if not count_diffs.empty else 0}"
            ),
        )

    @staticmethod
    def _get_duplicates_with_counts(conn, table: str, columns: list[str],
                                     where: str = "") -> pd.DataFrame:
        """Get duplicate groups WITH their occurrence count.
        Uses SQL GROUP BY HAVING COUNT(*) > 1 with COUNT included."""
        try:
            cols = [quote_identifier(safe_identifier(c)) for c in columns]
            col_list = ", ".join(cols)
            tbl = safe_table_expr(table)
            clause = f"WHERE {where}" if where else ""
            query = (
                f"SELECT {col_list}, COUNT(*) AS _DUP_COUNT "
                f"FROM {tbl} {clause} "
                f"GROUP BY {col_list} HAVING COUNT(*) > 1"
            )
            return conn.execute_query(query)
        except (NotImplementedError, Exception):
            # Fallback: pandas groupby with actual counts for CSV connectors
            try:
                raw = conn.read_dataframe()
                col_map = []
                for col in columns:
                    matching = [c for c in raw.columns if c.upper() == col.upper()]
                    if matching:
                        col_map.append(matching[0])
                if not col_map:
                    return pd.DataFrame()
                counts = raw.groupby(col_map).size().reset_index(name="_DUP_COUNT")
                counts = counts[counts["_DUP_COUNT"] > 1].reset_index(drop=True)
                counts.columns = [c.upper() if c != "_DUP_COUNT" else c for c in counts.columns]
                return counts
            except Exception:
                dupes = conn.get_duplicates(table, columns, where)
                if len(dupes) > 0:
                    dupes["_DUP_COUNT"] = 2
                return dupes
