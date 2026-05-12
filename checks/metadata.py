"""Metadata (schema) comparison check.

Best-in-class features:
- Precision, scale, and character length comparison (not just base type)
- Cross-platform type equivalence mapping (Teradata ↔ DuckDB ↔ pandas)
- Column ordering comparison (optional)
- WARNING for semantically equivalent but syntactically different types
- Detailed mismatch breakdown: type, precision, nullable, order
"""

import logging
import re

import pandas as pd

from .base import BaseCheck, CheckConfig, CheckResult, Status

logger = logging.getLogger(__name__)

# ── Cross-platform type equivalence groups ────────────────────────────────────
# Types within the same group are considered semantically compatible.
_TYPE_EQUIVALENCES: list[set[str]] = [
    {"INT", "INTEGER", "NUMBER(10,0)", "INT32", "INT64", "BIGINT", "NUMBER(19,0)",
     "NUMBER(5,0)", "NUMBER(3,0)", "SMALLINT", "BYTEINT", "TINYINT"},
    {"FLOAT", "DOUBLE", "FLOAT64", "REAL", "NUMBER"},
    {"VARCHAR", "STRING", "TEXT", "OBJECT", "CV", "CF"},
    {"DATE", "DATE32"},
    {"TIMESTAMP", "DATETIME", "TIMESTAMP_NTZ", "DATETIME64[NS]"},
    {"DECIMAL", "NUMERIC", "DEC"},
    {"BOOLEAN", "BOOL"},
]


def _normalize_type(dtype: str) -> str:
    """Strip whitespace, uppercase, collapse multiple spaces."""
    return re.sub(r"\s+", " ", str(dtype).strip().upper())


def _base_type(dtype: str) -> str:
    """Extract the base type name (before any parentheses).
    E.g. 'NUMBER(18,2)' → 'NUMBER', 'VARCHAR(200)' → 'VARCHAR'."""
    m = re.match(r"([A-Z_0-9]+)", _normalize_type(dtype))
    return m.group(1) if m else _normalize_type(dtype)


def _parse_precision_scale(dtype: str) -> tuple[int | None, int | None]:
    """Parse (precision, scale) from type like NUMBER(18,2) or VARCHAR(200)."""
    norm = _normalize_type(dtype)
    m = re.search(r"\((\d+)\s*,\s*(\d+)\)", norm)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"\((\d+)\)", norm)
    if m:
        return int(m.group(1)), None
    return None, None


def _types_equivalent(src_type: str, tgt_type: str) -> bool:
    """Check if two types are cross-platform equivalents."""
    src_base = _base_type(src_type)
    tgt_base = _base_type(tgt_type)
    if src_base == tgt_base:
        return True
    for group in _TYPE_EQUIVALENCES:
        if src_base in group and tgt_base in group:
            return True
    return False


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

        # Build detailed comparison on common columns
        rows: list[dict] = []
        type_mismatches = 0
        precision_mismatches = 0
        nullable_mismatches = 0
        equivalent_types = 0

        if common_cols:
            src_lookup = src_meta.set_index(src_meta["COLUMN_NAME"].str.upper())
            tgt_lookup = tgt_meta.set_index(tgt_meta["COLUMN_NAME"].str.upper())

            for col in common_cols:
                src_row = src_lookup.loc[col]
                tgt_row = tgt_lookup.loc[col]

                src_dtype = _normalize_type(src_row["DATA_TYPE"])
                tgt_dtype = _normalize_type(tgt_row["DATA_TYPE"])
                src_null = str(src_row["NULLABLE"]).strip().upper()
                tgt_null = str(tgt_row["NULLABLE"]).strip().upper()

                exact_type_match = src_dtype == tgt_dtype
                equiv_type = _types_equivalent(src_dtype, tgt_dtype) if not exact_type_match else True
                null_match = src_null == tgt_null

                # Precision / scale comparison
                src_prec, src_scale = _parse_precision_scale(src_dtype)
                tgt_prec, tgt_scale = _parse_precision_scale(tgt_dtype)
                prec_match = (src_prec == tgt_prec)
                scale_match = (src_scale == tgt_scale)

                has_issue = (not exact_type_match) or (not null_match) or (not prec_match) or (not scale_match)

                if has_issue:
                    issue_type = []
                    if not exact_type_match and not equiv_type:
                        issue_type.append("TYPE")
                        type_mismatches += 1
                    elif not exact_type_match and equiv_type:
                        issue_type.append("TYPE_EQUIVALENT")
                        equivalent_types += 1
                    if not prec_match or not scale_match:
                        issue_type.append("PRECISION")
                        precision_mismatches += 1
                    if not null_match:
                        issue_type.append("NULLABLE")
                        nullable_mismatches += 1

                    rows.append({
                        "COLUMN": col,
                        "SRC_DATA_TYPE": src_dtype,
                        "TGT_DATA_TYPE": tgt_dtype,
                        "DATA_TYPE_MATCH": exact_type_match,
                        "TYPE_EQUIVALENT": equiv_type,
                        "SRC_PRECISION": src_prec,
                        "TGT_PRECISION": tgt_prec,
                        "SRC_SCALE": src_scale,
                        "TGT_SCALE": tgt_scale,
                        "SRC_NULLABLE": src_null,
                        "TGT_NULLABLE": tgt_null,
                        "NULLABLE_MATCH": null_match,
                        "ISSUE": ", ".join(issue_type),
                    })

        # ── Column ordering comparison ────────────────────────────────────
        check_order = config.extra.get("check_column_order", False)
        order_mismatches = 0
        if check_order and common_cols:
            src_order = list(src_meta["COLUMN_NAME"].str.upper())
            tgt_order = list(tgt_meta["COLUMN_NAME"].str.upper())
            src_common_order = [c for c in src_order if c in set(common_cols)]
            tgt_common_order = [c for c in tgt_order if c in set(common_cols)]
            for i, (sc, tc) in enumerate(zip(src_common_order, tgt_common_order)):
                if sc != tc:
                    order_mismatches += 1

        # ── Status determination ──────────────────────────────────────────
        hard_issues = bool(only_in_src or only_in_tgt or type_mismatches or nullable_mismatches or precision_mismatches)
        soft_issues = equivalent_types > 0 or order_mismatches > 0

        if hard_issues:
            status = Status.FAIL
        elif soft_issues:
            status = Status.WARNING
        else:
            status = Status.PASS

        details_df = pd.DataFrame(rows) if rows else None

        metrics = {
            "src_column_count": len(src_cols),
            "tgt_column_count": len(tgt_cols),
            "columns_only_in_source": ", ".join(only_in_src) if only_in_src else "",
            "columns_only_in_target": ", ".join(only_in_tgt) if only_in_tgt else "",
            "type_mismatches": type_mismatches,
            "precision_mismatches": precision_mismatches,
            "nullable_mismatches": nullable_mismatches,
            "equivalent_types": equivalent_types,
        }
        if check_order:
            metrics["column_order_mismatches"] = order_mismatches

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics=metrics,
            details=details_df,
            message=(
                f"Src cols={len(src_cols)}, Tgt cols={len(tgt_cols)}, "
                f"Only in src={len(only_in_src)}, Only in tgt={len(only_in_tgt)}, "
                f"Type mismatches={type_mismatches}, Precision={precision_mismatches}, "
                f"Nullable={nullable_mismatches}, Equivalent types={equivalent_types}"
            ),
        )
