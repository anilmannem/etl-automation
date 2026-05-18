"""Row-level data comparison check with streaming, hash-first optimisation,
deterministic sampling, and column-level mismatch drill-down.

Advanced features:
- **Hash-first pass**: computes a per-row hash on the database side.
  Only rows whose hashes differ are fetched for column-level diff.
  Reduces network I/O by 90%+ on tables with <1% mismatches.
- **Streaming comparison**: uses server-side cursors to avoid loading
  entire tables into memory. Critical for tables >10M rows.
- **Deterministic sampling**: compare a stable subset of rows for
  quick smoke tests. Same rows selected on both sides via hash-mod.
- **Column-level drill-down**: for each mismatched row, identifies
  exactly which columns differ — not just "this row is different".
"""

from __future__ import annotations

import logging

import pandas as pd

from .base import BaseCheck, CheckConfig, CheckResult, Status
from ..connectors.base import safe_identifier, safe_identifiers, safe_table_expr, deterministic_sample_where

logger = logging.getLogger(__name__)


def _compute_match_pct(src_count: int, tgt_count: int,
                       rows_only_src: int, rows_only_tgt: int,
                       rows_with_diffs: int) -> float:
    """Compute match percentage accounting for all unmatched rows.

    Formula: matched = min(src, tgt) - rows_only_src - rows_only_tgt - rows_with_diffs
    (clamped to 0). Denominator is max(src, tgt) to penalise row-count gaps.
    """
    total = max(src_count, tgt_count)
    if total == 0:
        return 100.0
    matched = max(0, min(src_count, tgt_count) - rows_only_src - rows_only_tgt - rows_with_diffs)
    return round(matched / total * 100, 2)


def _build_row_hash_query(
    table: str, columns: list[str], where: str = "",
    key_columns: list[str] | None = None,
) -> str:
    """Build a SQL query that computes a deterministic hash per row.

    Uses Teradata HASHROW() for native server-side hashing. Only mismatched
    hashes need to be fetched for detailed comparison.
    """
    safe_cols = safe_identifiers(columns)
    hash_args = ", ".join(
        f'COALESCE(CAST("{c}" AS VARCHAR(1000)), \'NULL\')' for c in safe_cols
    )
    hash_expr = f"HASHROW({hash_args}) AS ROW_HASH"

    select_parts = [hash_expr]
    if key_columns:
        for k in safe_identifiers(key_columns):
            select_parts.insert(0, f'"{k}"')

    clause = f"WHERE {where}" if where else ""
    return f"SELECT {', '.join(select_parts)} FROM {safe_table_expr(table)} {clause}"


def _column_level_diff(
    src_row: pd.Series, tgt_row: pd.Series, ignore_cols: set[str]
) -> list[dict]:
    """Compare two aligned rows and return per-column diff details."""
    diffs = []
    for col in src_row.index:
        if col in ignore_cols or col.startswith("_"):
            continue
        sv = src_row[col]
        tv = tgt_row[col]
        if str(sv) != str(tv):
            diffs.append({"column": col, "source_value": sv, "target_value": tv})
    return diffs


class DataCheck(BaseCheck):
    """Row-level data comparison with multiple strategies.

    Strategies (selected automatically or via config):
    - ``hash``: hash-first pass, then fetch only mismatched rows
    - ``full``: fetch all data and compare in chunks (original approach)
    - ``sample``: deterministic sample comparison for smoke testing

    Auto-detects join keys when none are provided by finding columns that
    are unique in both source and target datasets.

    YAML config::

        - type: data
          join_keys: [ORDER_ID]
          chunk_size: 50000
          strategy: hash       # hash | full | sample
          sample_pct: 10       # for strategy=sample
          column_drill_down: true
    """
    name = "data"

    # ── Auto-detect key columns ──────────────────────────────────────────────

    @staticmethod
    def _auto_detect_keys_duckdb(con, src_upper, tgt_upper, common_upper):
        """Auto-detect columns suitable as join keys in a DuckDB connection.

        Checks for single columns (then column pairs) that have all-unique,
        non-null values in both source and target.  Prioritises columns with
        key-like names (id, _key, _pk, etc.) so the most likely candidate is
        tested first.
        """
        src_count = con.execute("SELECT count(*) FROM src").fetchone()[0]
        tgt_count = con.execute("SELECT count(*) FROM tgt").fetchone()[0]
        if src_count == 0 or tgt_count == 0:
            return []

        def _key_priority(col):
            cl = col.lower()
            if cl == "id" or cl.endswith("_id") or cl.endswith("_key") or cl.endswith("_pk"):
                return 0
            if "id" in cl or "key" in cl or "code" in cl or "num" in cl:
                return 1
            return 2

        sorted_cols = sorted(common_upper, key=_key_priority)

        # Phase 1: single columns
        for col in sorted_cols:
            try:
                src_ok = con.execute(
                    f'SELECT count(DISTINCT "{src_upper[col]}") = count(*) '
                    f'AND count("{src_upper[col]}") = count(*) FROM src'
                ).fetchone()[0]
                if not src_ok:
                    continue
                tgt_ok = con.execute(
                    f'SELECT count(DISTINCT "{tgt_upper[col]}") = count(*) '
                    f'AND count("{tgt_upper[col]}") = count(*) FROM tgt'
                ).fetchone()[0]
                if tgt_ok:
                    logger.info("Auto-detected key column: %s", col)
                    return [col]
            except Exception:
                continue

        # Phase 2: column pairs (limit search space)
        for i, c1 in enumerate(sorted_cols[:10]):
            for c2 in sorted_cols[i + 1 : 10]:
                try:
                    src_ok = con.execute(
                        f'SELECT count(*) FROM '
                        f'(SELECT DISTINCT "{src_upper[c1]}", "{src_upper[c2]}" FROM src)'
                    ).fetchone()[0] == src_count
                    if not src_ok:
                        continue
                    tgt_ok = con.execute(
                        f'SELECT count(*) FROM '
                        f'(SELECT DISTINCT "{tgt_upper[c1]}", "{tgt_upper[c2]}" FROM tgt)'
                    ).fetchone()[0] == tgt_count
                    if tgt_ok:
                        logger.info("Auto-detected composite key: [%s, %s]", c1, c2)
                        return [c1, c2]
                except Exception:
                    continue

        logger.info("No key columns auto-detected")
        return []

    @staticmethod
    def _auto_detect_keys_df(src_df, tgt_df):
        """Auto-detect join key columns from pandas DataFrames."""
        common_cols = [c for c in src_df.columns if c in tgt_df.columns]
        src_count = len(src_df)
        tgt_count = len(tgt_df)
        if src_count == 0 or tgt_count == 0:
            return None

        def _key_priority(col):
            cl = col.lower()
            if cl == "id" or cl.endswith("_id") or cl.endswith("_key") or cl.endswith("_pk"):
                return 0
            if "id" in cl or "key" in cl or "code" in cl or "num" in cl:
                return 1
            return 2

        sorted_cols = sorted(common_cols, key=_key_priority)

        for col in sorted_cols:
            if src_df[col].notna().all() and src_df[col].nunique() == src_count:
                if tgt_df[col].notna().all() and tgt_df[col].nunique() == tgt_count:
                    logger.info("Auto-detected key column: %s", col)
                    return [col]

        for i, c1 in enumerate(sorted_cols[:10]):
            for c2 in sorted_cols[i + 1 : 10]:
                if src_df.groupby([c1, c2]).ngroups == src_count:
                    if tgt_df.groupby([c1, c2]).ngroups == tgt_count:
                        logger.info("Auto-detected composite key: [%s, %s]", c1, c2)
                        return [c1, c2]

        logger.info("No key columns auto-detected")
        return None

    # ── DuckDB no-key fallback with EXCEPT ALL + best-match pairing ──────────

    @staticmethod
    def _duckdb_no_key_diff(con, src_upper, tgt_upper, common_upper,
                            max_mismatches):
        """Accurate no-key diff via EXCEPT ALL with best-match row pairing.

        EXCEPT ALL preserves duplicates (unlike EXCEPT).  After finding the
        rows that exist on only one side, we greedily pair source-only with
        target-only rows by maximum column overlap so we can report
        cell-level diffs instead of just ``(not in target)``.
        """
        src_sel = ", ".join(f'"{src_upper[c]}"' for c in common_upper)
        tgt_sel = ", ".join(f'"{tgt_upper[c]}"' for c in common_upper)

        # EXCEPT ALL: duplicate-aware set difference
        con.execute(f"""
            CREATE TABLE _src_only AS
            SELECT ROW_NUMBER() OVER () AS _rn, * FROM (
                SELECT {src_sel} FROM src EXCEPT ALL SELECT {tgt_sel} FROM tgt
            )
        """)
        con.execute(f"""
            CREATE TABLE _tgt_only AS
            SELECT ROW_NUMBER() OVER () AS _rn, * FROM (
                SELECT {tgt_sel} FROM tgt EXCEPT ALL SELECT {src_sel} FROM src
            )
        """)

        rows_only_src = con.execute("SELECT count(*) FROM _src_only").fetchone()[0]
        rows_only_tgt = con.execute("SELECT count(*) FROM _tgt_only").fetchone()[0]

        column_details: list[dict] = []

        # Best-match pairing: pair src-only with tgt-only rows that share
        # the most column values, then diff the remaining columns.
        if rows_only_src > 0 and rows_only_tgt > 0:
            max_pair = min(500, rows_only_src, rows_only_tgt)

            match_score = " + ".join(
                f'CASE WHEN s."{src_upper[c]}" IS NOT DISTINCT FROM '
                f't."{tgt_upper[c]}" THEN 1 ELSE 0 END'
                for c in common_upper
            )

            pair_rows = con.execute(f"""
                WITH scores AS (
                    SELECT s._rn AS src_rn, t._rn AS tgt_rn,
                           ({match_score}) AS score
                    FROM (SELECT * FROM _src_only WHERE _rn <= {max_pair}) s
                    CROSS JOIN (SELECT * FROM _tgt_only WHERE _rn <= {max_pair}) t
                )
                SELECT src_rn, tgt_rn, score FROM scores
                WHERE score > 0
                ORDER BY score DESC
                LIMIT {max_pair * 10}
            """).fetchall()

            # Greedy assignment: highest-overlap pair first
            used_src, used_tgt = set(), set()
            paired = []
            for src_rn, tgt_rn, score in pair_rows:
                if src_rn not in used_src and tgt_rn not in used_tgt:
                    paired.append((int(src_rn), int(tgt_rn)))
                    used_src.add(src_rn)
                    used_tgt.add(tgt_rn)

            # Fetch paired rows and diff column-by-column
            if paired:
                pair_values = ", ".join(f"({s}, {t})" for s, t in paired)
                select_parts = ['p.col0 AS "_ROW"']
                for c in common_upper:
                    select_parts.append(f's."{src_upper[c]}" AS "_src_{c}"')
                    select_parts.append(f't."{tgt_upper[c]}" AS "_tgt_{c}"')

                drill_sql = (
                    f"SELECT {', '.join(select_parts)} "
                    f"FROM (VALUES {pair_values}) AS p(col0, col1) "
                    f"JOIN _src_only s ON s._rn = p.col0 "
                    f"JOIN _tgt_only t ON t._rn = p.col1"
                )
                result_cols = (
                    ["_ROW"]
                    + [col for c in common_upper
                       for col in (f"_src_{c}", f"_tgt_{c}")]
                )
                for row_tuple in con.execute(drill_sql).fetchall():
                    row = dict(zip(result_cols, row_tuple))
                    for c in common_upper:
                        sv, tv = row[f"_src_{c}"], row[f"_tgt_{c}"]
                        if sv is None and tv is None:
                            continue
                        if sv is not None and tv is not None:
                            try:
                                if float(sv) == float(tv):
                                    continue
                            except (ValueError, TypeError):
                                pass
                        if str(sv) != str(tv):
                            column_details.append({
                                "ROW": row["_ROW"],
                                "COLUMN": c,
                                "SOURCE_VALUE": str(sv) if sv is not None else "NULL",
                                "TARGET_VALUE": str(tv) if tv is not None else "NULL",
                            })
                    if len(column_details) >= max_mismatches:
                        break

            # Paired rows are "changed", not "only on one side"
            rows_only_src -= len(used_src)
            rows_only_tgt -= len(used_tgt)

        return column_details, rows_only_src, rows_only_tgt

    def run(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:
        logger.info("Running data check: %s → %s", config.source_table, config.target_table)

        src_is_file = hasattr(src_conn, "read_dataframe")
        tgt_is_file = hasattr(tgt_conn, "read_dataframe")

        if src_is_file and tgt_is_file:
            # CSV ↔ CSV (or any two file-based connectors) — pure DuckDB
            return self._duckdb_strategy(src_conn, tgt_conn, config)

        if src_is_file or tgt_is_file:
            # Mixed: one side is a file, the other is a SQL DB (e.g. CSV ↔ Teradata)
            # Stream the SQL side into DuckDB in chunks, then diff both in-engine.
            return self._duckdb_bridge_strategy(src_conn, tgt_conn, config)

        # ── Pyramid Validation: aggregate-first shortcut ─────────────────────
        # If pyramid mode is enabled (default for DB↔DB), do a quick aggregate
        # pre-check. If row counts + SUMs match, skip the expensive comparison.
        use_pyramid = config.extra.get("pyramid", True)  # enabled by default
        if use_pyramid and not config.extra.get("_pyramid_done"):
            try:
                from ..engine.intelligent import pyramid_aggregate_check
                # Pass key column for distinct-key and range checks
                key_col = config.join_keys[0] if config.join_keys and config.join_keys != ["NA"] else None
                pyramid_result = pyramid_aggregate_check(
                    src_conn, tgt_conn,
                    config.source_table, config.target_table,
                    key_column=key_col,
                    where=config.where,
                )
                if pyramid_result["passed"]:
                    logger.info("FINGERPRINT PASS: %s — skipping detailed comparison",
                                pyramid_result["reason"])
                    return CheckResult(
                        check_type=self.name,
                        status=Status.PASS,
                        metrics={
                            "src_row_count": pyramid_result["src_count"],
                            "tgt_row_count": pyramid_result["tgt_count"],
                            "match_pct": 100.0,
                            "rows_only_in_source": 0,
                            "rows_only_in_target": 0,
                            "rows_with_diffs": 0,
                            "comparison_mode": "fingerprint",
                            "join_keys_used": key_col or "auto-detected",
                            "strategy": "fingerprint",
                            "layer": pyramid_result.get("layer", 1),
                        },
                        message=f"FINGERPRINT PASS: {pyramid_result['reason']}",
                    )
                else:
                    logger.info("FINGERPRINT FAIL: %s — drilling into detailed comparison (diagnostics: %s)",
                                pyramid_result["reason"], pyramid_result.get("diagnostics", []))
            except Exception as e:
                logger.debug("Fingerprint pre-check failed (non-fatal): %s", e)

        # ── Adaptive Strategy Selection ──────────────────────────────────────
        strategy = config.extra.get("strategy", "auto")
        sample_pct = config.extra.get("sample_pct", 10)

        if strategy == "auto":
            try:
                from ..engine.intelligent import select_optimal_strategy, IntelligentStore
                store = IntelligentStore()
                recommendation = select_optimal_strategy(
                    src_conn, tgt_conn, config.source_table, store=store,
                )
                strategy = recommendation.strategy
                logger.info("ADAPTIVE: Selected '%s' strategy — %s",
                            strategy, recommendation.reason)
                store.close()
            except Exception as e:
                logger.debug("Adaptive selection failed (non-fatal): %s — defaulting to full", e)
                strategy = "full"

        # Auto-select minus strategy when both sides are Teradata (same instance)
        if strategy == "minus" or (
            strategy == "full"
            and hasattr(src_conn, 'config') and hasattr(tgt_conn, 'config')
            and src_conn.config.platform == "teradata"
            and tgt_conn.config.platform == "teradata"
            and src_conn.config.dsn == tgt_conn.config.dsn
        ):
            return self._minus_strategy(src_conn, tgt_conn, config)

        if strategy == "hash":
            return self._hash_strategy(src_conn, tgt_conn, config)
        elif strategy == "sample":
            return self._sample_strategy(src_conn, tgt_conn, config, sample_pct)
        else:
            return self._full_strategy(src_conn, tgt_conn, config)

    # ── Strategy: MINUS (Teradata ↔ Teradata, same instance) ─────────────────

    def _minus_strategy(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:
        """Server-side MINUS in Teradata — only transfers mismatched rows.

        Runs:
          SELECT cols FROM src MINUS SELECT cols FROM tgt  → rows only in source
          SELECT cols FROM tgt MINUS SELECT cols FROM src  → rows only in target

        Then performs column-level drill-down on the transferred diff rows
        using join keys (or positional pairing if no keys).
        """
        logger.info("Using MINUS strategy (Teradata server-side diff)")

        src_table = config.source_table
        tgt_table = config.target_table
        where = config.where
        join_keys = config.join_keys if config.join_keys and config.join_keys != ["NA"] else None
        max_mismatches = config.extra.get("max_mismatches", 10_000)

        # Get columns (from target, excluding ignored)
        src_cols = tgt_conn.get_column_names(tgt_table, exclude=config.ignore_columns)
        col_list = ", ".join(f'"{c}"' for c in src_cols)
        clause = f"WHERE {where}" if where else ""

        # Get row counts first (cheap single-AMP queries)
        src_count = src_conn.get_row_count(src_table, where)
        tgt_count = tgt_conn.get_row_count(tgt_table, where)

        # MINUS queries — executed entirely in Teradata
        minus_src_query = (
            f"SELECT {col_list} FROM {src_table} {clause} "
            f"MINUS "
            f"SELECT {col_list} FROM {tgt_table} {clause}"
        )
        minus_tgt_query = (
            f"SELECT {col_list} FROM {tgt_table} {clause} "
            f"MINUS "
            f"SELECT {col_list} FROM {src_table} {clause}"
        )

        logger.info("Executing MINUS (rows only in source)...")
        only_in_src_df = src_conn.execute_query(minus_src_query)
        only_in_src_df.columns = [c.upper() for c in only_in_src_df.columns]

        logger.info("Executing MINUS (rows only in target)...")
        only_in_tgt_df = tgt_conn.execute_query(minus_tgt_query)
        only_in_tgt_df.columns = [c.upper() for c in only_in_tgt_df.columns]

        rows_only_src = len(only_in_src_df)
        rows_only_tgt = len(only_in_tgt_df)

        logger.info("MINUS results: %d only-in-src, %d only-in-tgt (transferred %d rows total)",
                    rows_only_src, rows_only_tgt, rows_only_src + rows_only_tgt)

        # Auto-detect join keys from the diff rows if not provided
        if not join_keys and rows_only_src > 0 and rows_only_tgt > 0:
            join_keys = self._auto_detect_keys_df(only_in_src_df, only_in_tgt_df)

        # Column-level drill-down on the diff rows
        mismatch_cols = ""
        col_mismatch_summary = ""
        details = None
        rows_with_diffs = 0

        if join_keys and rows_only_src > 0 and rows_only_tgt > 0:
            # Keyed drill-down: pair by join keys, find which columns differ
            details, mismatch_cols, col_mismatch_summary = self._column_drill_down(
                only_in_src_df, only_in_tgt_df, join_keys, config.ignore_columns, max_mismatches
            )
            # Rows that paired on keys = changed rows (not truly "only in one side")
            key_upper = [k.upper() for k in join_keys]
            paired = only_in_src_df.merge(only_in_tgt_df, on=key_upper, how="inner", suffixes=("", "_"))
            rows_with_diffs = len(paired)
            rows_only_src = rows_only_src - rows_with_diffs
            rows_only_tgt = rows_only_tgt - rows_with_diffs
        elif rows_only_src > 0 or rows_only_tgt > 0:
            # No keys — show raw diff rows
            details = self._build_details(only_in_src_df, only_in_tgt_df, max_mismatches)

        match_pct = _compute_match_pct(src_count, tgt_count, rows_only_src, rows_only_tgt, rows_with_diffs)
        is_match = rows_only_src == 0 and rows_only_tgt == 0 and rows_with_diffs == 0
        status = Status.PASS if is_match else Status.FAIL

        key_display = ", ".join(k.upper() for k in join_keys) if join_keys else "none"

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={
                "src_row_count": src_count,
                "tgt_row_count": tgt_count,
                "rows_only_in_source": rows_only_src,
                "rows_only_in_target": rows_only_tgt,
                "rows_with_diffs": rows_with_diffs,
                "rows_matched": max(src_count, tgt_count) - rows_only_src - rows_only_tgt - rows_with_diffs,
                "match_pct": match_pct,
                "mismatch_columns": mismatch_cols,
                "column_mismatch_summary": col_mismatch_summary,
                "comparison_mode": "keyed" if join_keys else "positional",
                "join_keys_used": key_display,
                "strategy": "minus",
            },
            details=details,
            message=(
                f"Source={src_count:,}, Target={tgt_count:,}, "
                f"match={match_pct}%, strategy=MINUS (server-side), "
                f"keys={key_display}, "
                f"rows_with_diffs={rows_with_diffs}, "
                f"Only-in-src={rows_only_src:,}, Only-in-tgt={rows_only_tgt:,}"
            ),
        )

    # ── Strategy 0: DuckDB-native (CSV / Excel / any DataFrame connector) ─────

    def _duckdb_strategy(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:  # noqa: C901
        """Large-scale diff via DuckDB — vectorized, streaming, spills to disk.

        Why DuckDB instead of pandas:
        - Reads CSV files directly via read_csv_auto() — no full in-memory load
        - Vectorized columnar engine: 10-100x faster than pandas on large data
        - Automatic spill-to-disk: handles files far bigger than available RAM
        - NULL-safe comparison via IS DISTINCT FROM — no extra NaN handling
        - Anti-join for only-src/only-tgt is O(n) not O(n²)
        """
        import duckdb
        from collections import Counter

        logger.info("Using DUCKDB strategy for data comparison")

        con = duckdb.connect()  # in-memory; spills to disk automatically

        # Prefer direct file path (zero-copy streaming) over loading a DataFrame
        src_path = getattr(src_conn, "_file_path", None)
        tgt_path = getattr(tgt_conn, "_file_path", None)

        loaded = False
        if src_path and tgt_path:
            try:
                con.execute(f"CREATE VIEW src AS SELECT * FROM read_csv_auto({src_path!r})")
                con.execute(f"CREATE VIEW tgt AS SELECT * FROM read_csv_auto({tgt_path!r})")
                loaded = True
                logger.debug("DuckDB reading CSV files directly: %s | %s", src_path, tgt_path)
            except Exception as exc:
                logger.warning("DuckDB direct file read failed (%s), falling back to pandas", exc)
                # Clean up any partial views
                con.execute("DROP VIEW IF EXISTS src")
                con.execute("DROP VIEW IF EXISTS tgt")

        if not loaded:
            src_df = src_conn.read_dataframe()
            tgt_df = tgt_conn.read_dataframe()
            con.register("_src_df", src_df)
            con.register("_tgt_df", tgt_df)
            con.execute("CREATE VIEW src AS SELECT * FROM _src_df")
            con.execute("CREATE VIEW tgt AS SELECT * FROM _tgt_df")
            logger.debug("DuckDB registered in-memory DataFrames")

        # Discover columns — DuckDB is case-insensitive but we normalise to UPPER
        src_upper = {r[0].upper(): r[0] for r in con.execute("DESCRIBE src").fetchall()}
        tgt_upper = {r[0].upper(): r[0] for r in con.execute("DESCRIBE tgt").fetchall()}

        ignore_set = {c.upper() for c in (config.ignore_columns or [])}
        common_upper = [c for c in src_upper if c in tgt_upper and c not in ignore_set]
        join_keys_u = (
            [k.upper() for k in config.join_keys]
            if config.join_keys and config.join_keys != ["NA"]
            else []
        )
        # Validate join keys exist in both sources
        if join_keys_u:
            missing = [k for k in join_keys_u if k not in src_upper or k not in tgt_upper]
            if missing:
                logger.warning("Join keys missing from schema: %s — positional fallback", missing)
                join_keys_u = []

        # Auto-detect keys if none provided
        if not join_keys_u:
            join_keys_u = self._auto_detect_keys_duckdb(
                con, src_upper, tgt_upper, common_upper
            )

        max_mismatches = config.extra.get("max_mismatches", 10_000)

        src_count = con.execute("SELECT count(*) FROM src").fetchone()[0]
        tgt_count = con.execute("SELECT count(*) FROM tgt").fetchone()[0]
        rows_only_src = 0
        rows_only_tgt = 0
        column_details: list[dict] = []

        if join_keys_u:
            data_cols = [c for c in common_upper if c not in join_keys_u]

            # NULL-safe join condition
            key_join = " AND ".join(
                f's."{src_upper[k]}" = t."{tgt_upper[k]}"' for k in join_keys_u
            )

            # Anti-joins: O(n) existence checks — far faster than set subtraction in Python
            rows_only_src = con.execute(
                f"SELECT count(*) FROM src s WHERE NOT EXISTS "
                f"(SELECT 1 FROM tgt t WHERE {key_join})"
            ).fetchone()[0]
            rows_only_tgt = con.execute(
                f"SELECT count(*) FROM tgt t WHERE NOT EXISTS "
                f"(SELECT 1 FROM src s WHERE {key_join})"
            ).fetchone()[0]

            if data_cols:
                # Filter to only rows with at least one differing cell
                # IS DISTINCT FROM handles NULLs natively — no Python NaN dance
                diff_filter = " OR ".join(
                    f's."{src_upper[c]}" IS DISTINCT FROM t."{tgt_upper[c]}"'
                    for c in data_cols
                )
                select_parts = (
                    [f's."{src_upper[k]}" AS "_key_{k}"' for k in join_keys_u]
                    + [col for c in data_cols
                       for col in (
                           f's."{src_upper[c]}" AS "_src_{c}"',
                           f't."{tgt_upper[c]}" AS "_tgt_{c}"',
                       )]
                )
                diff_sql = (
                    f"SELECT {', '.join(select_parts)} "
                    f"FROM src s INNER JOIN tgt t ON {key_join} "
                    f"WHERE {diff_filter} "
                    f"LIMIT {max_mismatches}"
                )
                result_cols = (
                    [f"_key_{k}" for k in join_keys_u]
                    + [col for c in data_cols for col in (f"_src_{c}", f"_tgt_{c}")]
                )
                for row_tuple in con.execute(diff_sql).fetchall():
                    row = dict(zip(result_cols, row_tuple))
                    for c in data_cols:
                        sv, tv = row[f"_src_{c}"], row[f"_tgt_{c}"]
                        if sv is None and tv is None:
                            continue
                        # Suppress numeric equivalence noise (e.g. 30.0 vs 30)
                        if sv is not None and tv is not None:
                            try:
                                if float(sv) == float(tv):
                                    continue
                            except (ValueError, TypeError):
                                pass
                        if str(sv) != str(tv):
                            detail = {
                                "COLUMN": c,
                                "SOURCE_VALUE": str(sv) if sv is not None else "NULL",
                                "TARGET_VALUE": str(tv) if tv is not None else "NULL",
                            }
                            if len(join_keys_u) == 1:
                                detail[join_keys_u[0]] = row[f"_key_{join_keys_u[0]}"]
                            else:
                                for k in join_keys_u:
                                    detail[k] = row[f"_key_{k}"]
                            column_details.append(detail)
                        if len(column_details) >= max_mismatches:
                            break
                    if len(column_details) >= max_mismatches:
                        break
        else:
            # No keys even after auto-detect — EXCEPT ALL + best-match pairing
            column_details, rows_only_src, rows_only_tgt = self._duckdb_no_key_diff(
                con, src_upper, tgt_upper, common_upper, max_mismatches
            )

        con.close()

        col_counts = Counter(d["COLUMN"] for d in column_details)
        mismatch_cols = ", ".join(sorted(col_counts.keys()))
        col_summary = ", ".join(f"{c}:{n}" for c, n in col_counts.most_common(10))

        unique_key = join_keys_u[0] if join_keys_u else "ROW"
        rows_with_diffs = len({d.get(unique_key) for d in column_details}) if column_details else 0
        comparison_mode = "keyed" if join_keys_u else "positional"
        match_pct = _compute_match_pct(src_count, tgt_count, rows_only_src, rows_only_tgt, rows_with_diffs)
        total_mismatches = len(column_details) + rows_only_src + rows_only_tgt
        status = Status.PASS if total_mismatches == 0 else Status.FAIL
        details = pd.DataFrame(column_details) if column_details else None

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={
                "src_row_count": src_count,
                "tgt_row_count": tgt_count,
                "rows_only_in_source": rows_only_src,
                "rows_only_in_target": rows_only_tgt,
                "rows_with_diffs": rows_with_diffs,
                "cell_diffs_found": len(column_details),
                "mismatch_columns": mismatch_cols,
                "column_mismatch_summary": col_summary,
                "match_pct": match_pct,
                "comparison_mode": comparison_mode,
                "join_keys_used": ", ".join(join_keys_u) if join_keys_u else "none",
                "strategy": "duckdb",
            },
            details=details,
            message=(
                f"DuckDB diff: src={src_count:,}, tgt={tgt_count:,}, "
                f"only_src={rows_only_src:,}, only_tgt={rows_only_tgt:,}, "
                f"cell_diffs={len(column_details):,}, match={match_pct}%"
                + (f", keys=[{', '.join(join_keys_u)}]" if join_keys_u else ", keys=none (positional)")
                + (f", diff_cols=[{mismatch_cols}]" if mismatch_cols else "")
            ),
        )

    # ── Strategy 0b: DuckDB bridge (CSV ↔ SQL DB, e.g. CSV ↔ Teradata) ────────

    def _duckdb_bridge_strategy(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:  # noqa: C901
        """Diff a file-based connector against a SQL connector via DuckDB.

        The SQL side is streamed in chunks into a DuckDB table so nothing
        is fully held in Python memory. The file side is read by DuckDB
        natively (zero-copy for CSV). The actual diff runs entirely inside
        the DuckDB vectorized engine — same efficiency as the pure CSV path.
        """
        import duckdb
        from collections import Counter

        logger.info("Using DUCKDB BRIDGE strategy (mixed file ↔ SQL comparison)")

        src_is_file = hasattr(src_conn, "read_dataframe")
        # Normalise: file connector → "src", SQL connector → "db"
        file_conn = src_conn if src_is_file else tgt_conn
        db_conn   = tgt_conn if src_is_file else src_conn
        db_table  = config.target_table if src_is_file else config.source_table

        con = duckdb.connect()

        # ── Load file side ────────────────────────────────────────────────────
        file_path = getattr(file_conn, "_file_path", None)
        if file_path:
            con.execute(f"CREATE VIEW file_side AS SELECT * FROM read_csv_auto({file_path!r})")
            logger.debug("DuckDB: CSV side from file %s", file_path)
        else:
            fdf = file_conn.read_dataframe()
            con.register("_fdf", fdf)
            con.execute("CREATE VIEW file_side AS SELECT * FROM _fdf")
            logger.debug("DuckDB: file side from in-memory DataFrame")

        # ── Stream SQL side chunk-by-chunk into a DuckDB table ───────────────
        chunk_size = config.chunk_size  # default 50_000 from CheckConfig
        fetch_sql = f"SELECT * FROM {db_table}"
        if config.where:
            fetch_sql += f" WHERE {config.where}"

        first = True
        total_db_rows = 0
        logger.debug("Streaming SQL side into DuckDB: %s", fetch_sql)
        for chunk in db_conn.execute_streaming(fetch_sql, chunk_size):
            chunk.columns = [c.upper() for c in chunk.columns]
            total_db_rows += len(chunk)
            if first:
                con.register("_chunk", chunk)
                con.execute("CREATE TABLE db_side AS SELECT * FROM _chunk")
                first = False
            else:
                con.register("_chunk", chunk)
                con.execute("INSERT INTO db_side SELECT * FROM _chunk")
        if first:
            # No rows from DB — create empty table from schema
            con.execute("CREATE TABLE db_side AS SELECT * FROM file_side WHERE false")

        logger.info("SQL side streamed: %d rows into DuckDB", total_db_rows)

        # Assign src/tgt views respecting original direction
        if src_is_file:
            con.execute("CREATE VIEW src AS SELECT * FROM file_side")
            con.execute("CREATE VIEW tgt AS SELECT * FROM db_side")
        else:
            con.execute("CREATE VIEW src AS SELECT * FROM db_side")
            con.execute("CREATE VIEW tgt AS SELECT * FROM file_side")

        # ── From here: identical logic to _duckdb_strategy ───────────────────
        src_upper = {r[0].upper(): r[0] for r in con.execute("DESCRIBE src").fetchall()}
        tgt_upper = {r[0].upper(): r[0] for r in con.execute("DESCRIBE tgt").fetchall()}

        ignore_set = {c.upper() for c in (config.ignore_columns or [])}
        common_upper = [c for c in src_upper if c in tgt_upper and c not in ignore_set]
        join_keys_u = (
            [k.upper() for k in config.join_keys]
            if config.join_keys and config.join_keys != ["NA"]
            else []
        )
        if join_keys_u:
            missing = [k for k in join_keys_u if k not in src_upper or k not in tgt_upper]
            if missing:
                logger.warning("Join keys missing: %s — positional fallback", missing)
                join_keys_u = []

        # Auto-detect keys if none provided
        if not join_keys_u:
            join_keys_u = self._auto_detect_keys_duckdb(
                con, src_upper, tgt_upper, common_upper
            )

        max_mismatches = config.extra.get("max_mismatches", 10_000)
        src_count = con.execute("SELECT count(*) FROM src").fetchone()[0]
        tgt_count = con.execute("SELECT count(*) FROM tgt").fetchone()[0]
        rows_only_src = 0
        rows_only_tgt = 0
        column_details: list[dict] = []

        if join_keys_u:
            data_cols = [c for c in common_upper if c not in join_keys_u]
            key_join = " AND ".join(
                f's."{src_upper[k]}" = t."{tgt_upper[k]}"' for k in join_keys_u
            )
            rows_only_src = con.execute(
                f"SELECT count(*) FROM src s WHERE NOT EXISTS "
                f"(SELECT 1 FROM tgt t WHERE {key_join})"
            ).fetchone()[0]
            rows_only_tgt = con.execute(
                f"SELECT count(*) FROM tgt t WHERE NOT EXISTS "
                f"(SELECT 1 FROM src s WHERE {key_join})"
            ).fetchone()[0]
            if data_cols:
                diff_filter = " OR ".join(
                    f's."{src_upper[c]}" IS DISTINCT FROM t."{tgt_upper[c]}"'
                    for c in data_cols
                )
                select_parts = (
                    [f's."{src_upper[k]}" AS "_key_{k}"' for k in join_keys_u]
                    + [col for c in data_cols
                       for col in (
                           f's."{src_upper[c]}" AS "_src_{c}"',
                           f't."{tgt_upper[c]}" AS "_tgt_{c}"',
                       )]
                )
                diff_sql = (
                    f"SELECT {', '.join(select_parts)} "
                    f"FROM src s INNER JOIN tgt t ON {key_join} "
                    f"WHERE {diff_filter} "
                    f"LIMIT {max_mismatches}"
                )
                result_cols = (
                    [f"_key_{k}" for k in join_keys_u]
                    + [col for c in data_cols for col in (f"_src_{c}", f"_tgt_{c}")]
                )
                for row_tuple in con.execute(diff_sql).fetchall():
                    row = dict(zip(result_cols, row_tuple))
                    for c in data_cols:
                        sv, tv = row[f"_src_{c}"], row[f"_tgt_{c}"]
                        if sv is None and tv is None:
                            continue
                        if sv is not None and tv is not None:
                            try:
                                if float(sv) == float(tv):
                                    continue
                            except (ValueError, TypeError):
                                pass
                        if str(sv) != str(tv):
                            detail = {
                                "COLUMN": c,
                                "SOURCE_VALUE": str(sv) if sv is not None else "NULL",
                                "TARGET_VALUE": str(tv) if tv is not None else "NULL",
                            }
                            if len(join_keys_u) == 1:
                                detail[join_keys_u[0]] = row[f"_key_{join_keys_u[0]}"]
                            else:
                                for k in join_keys_u:
                                    detail[k] = row[f"_key_{k}"]
                            column_details.append(detail)
                        if len(column_details) >= max_mismatches:
                            break
                    if len(column_details) >= max_mismatches:
                        break
        else:
            # No keys even after auto-detect — EXCEPT ALL + best-match pairing
            column_details, rows_only_src, rows_only_tgt = self._duckdb_no_key_diff(
                con, src_upper, tgt_upper, common_upper, max_mismatches
            )

        con.close()

        col_counts = Counter(d["COLUMN"] for d in column_details)
        mismatch_cols = ", ".join(sorted(col_counts.keys()))
        col_summary = ", ".join(f"{c}:{n}" for c, n in col_counts.most_common(10))
        unique_key = join_keys_u[0] if join_keys_u else "ROW"
        rows_with_diffs = len({d.get(unique_key) for d in column_details}) if column_details else 0
        comparison_mode = "keyed" if join_keys_u else "positional"
        match_pct = _compute_match_pct(src_count, tgt_count, rows_only_src, rows_only_tgt, rows_with_diffs)
        total_mismatches = len(column_details) + rows_only_src + rows_only_tgt
        status = Status.PASS if total_mismatches == 0 else Status.FAIL
        details = pd.DataFrame(column_details) if column_details else None

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={
                "src_row_count": src_count,
                "tgt_row_count": tgt_count,
                "rows_only_in_source": rows_only_src,
                "rows_only_in_target": rows_only_tgt,
                "rows_with_diffs": rows_with_diffs,
                "cell_diffs_found": len(column_details),
                "mismatch_columns": mismatch_cols,
                "column_mismatch_summary": col_summary,
                "match_pct": match_pct,
                "comparison_mode": comparison_mode,
                "join_keys_used": ", ".join(join_keys_u) if join_keys_u else "none",
                "strategy": "duckdb_bridge",
            },
            details=details,
            message=(
                f"DuckDB bridge diff: src={src_count:,}, tgt={tgt_count:,}, "
                f"only_src={rows_only_src:,}, only_tgt={rows_only_tgt:,}, "
                f"cell_diffs={len(column_details):,}, match={match_pct}%"
                + (f", keys=[{', '.join(join_keys_u)}]" if join_keys_u else ", keys=none (positional)")
                + (f", diff_cols=[{mismatch_cols}]" if mismatch_cols else "")
            ),
        )

    # ── Strategy 1: Hash-first pass ──────────────────────────────────────────

    def _hash_strategy(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:
        """Compare row hashes server-side. Fetch full data only for mismatches."""
        logger.info("Using HASH strategy for data comparison")

        join_keys = config.join_keys if config.join_keys and config.join_keys != ["NA"] else None
        if not join_keys:
            logger.info("Hash strategy requires join_keys — falling back to full")
            return self._full_strategy(src_conn, tgt_conn, config)

        columns = tgt_conn.get_column_names(config.target_table, exclude=config.ignore_columns)
        where = config.where

        # Phase 1: compute hashes on both sides (streamed for large tables)
        src_hash_q = _build_row_hash_query(config.source_table, columns, where, join_keys)
        tgt_hash_q = _build_row_hash_query(config.target_table, columns, where, join_keys)

        logger.info("Phase 1: fetching row hashes")
        chunk_size = config.chunk_size

        # Stream hashes in chunks to avoid OOM on large tables
        try:
            src_chunks = []
            for chunk in src_conn.execute_streaming(src_hash_q, chunk_size):
                chunk.columns = [c.upper() for c in chunk.columns]
                src_chunks.append(chunk)
            src_hashes = pd.concat(src_chunks, ignore_index=True) if src_chunks else pd.DataFrame()

            tgt_chunks = []
            for chunk in tgt_conn.execute_streaming(tgt_hash_q, chunk_size):
                chunk.columns = [c.upper() for c in chunk.columns]
                tgt_chunks.append(chunk)
            tgt_hashes = pd.concat(tgt_chunks, ignore_index=True) if tgt_chunks else pd.DataFrame()
        except Exception as e:
            logger.warning("Hash strategy failed (%s) — falling back to full strategy", e)
            return self._full_strategy(src_conn, tgt_conn, config)

        src_count = len(src_hashes)
        tgt_count = len(tgt_hashes)

        # Merge on keys + hash to find mismatches
        key_upper = [k.upper() for k in join_keys]
        merged = src_hashes.merge(
            tgt_hashes, on=key_upper, how="outer",
            suffixes=("_SRC", "_TGT"), indicator=True,
        )

        only_src_keys = merged[merged["_merge"] == "left_only"][key_upper]
        only_tgt_keys = merged[merged["_merge"] == "right_only"][key_upper]
        both = merged[merged["_merge"] == "both"]
        hash_mismatches = both[both["ROW_HASH_SRC"] != both["ROW_HASH_TGT"]][key_upper]

        n_only_src = len(only_src_keys)
        n_only_tgt = len(only_tgt_keys)
        n_hash_diff = len(hash_mismatches)
        total_mismatches = n_only_src + n_only_tgt + n_hash_diff

        logger.info(
            "Phase 1 results: only_src=%d, only_tgt=%d, hash_diff=%d",
            n_only_src, n_only_tgt, n_hash_diff,
        )

        # Phase 2: fetch full rows only for mismatched keys (column drill-down)
        max_fetch = config.extra.get("max_mismatches", 10_000)
        column_details = []
        do_drill_down = config.extra.get("column_drill_down", True)
        batch_size = 100  # fetch this many rows per query instead of one-by-one

        if do_drill_down and n_hash_diff > 0:
            drill_keys = hash_mismatches.head(min(n_hash_diff, max_fetch))
            col_list = ", ".join(f'"{c}"' for c in columns)
            ignore_set = {c.upper() for c in config.ignore_columns}

            # Batch drill-down: build IN clauses for groups of keys
            for batch_start in range(0, len(drill_keys), batch_size):
                batch = drill_keys.iloc[batch_start:batch_start + batch_size]

                if len(key_upper) == 1:
                    # Single-column key: use efficient IN clause
                    k = key_upper[0]
                    vals = ", ".join(
                        f"'{str(row[k]).replace(chr(39), chr(39)+chr(39))}'"
                        for _, row in batch.iterrows()
                    )
                    key_clause = f'"{k}" IN ({vals})'
                else:
                    # Multi-column key: use OR of AND conditions
                    or_parts = []
                    for _, key_row in batch.iterrows():
                        and_parts = []
                        for k in key_upper:
                            escaped_val = str(key_row[k]).replace("'", "''")
                            and_parts.append(f'"{k}" = \'{escaped_val}\'')
                        or_parts.append(f"({' AND '.join(and_parts)})")
                    key_clause = " OR ".join(or_parts)

                full_where = f"{where} AND ({key_clause})" if where else key_clause

                src_batch_df = src_conn.execute_query(
                    f'SELECT {col_list} FROM {config.source_table} WHERE {full_where}'
                )
                tgt_batch_df = tgt_conn.execute_query(
                    f'SELECT {col_list} FROM {config.target_table} WHERE {full_where}'
                )

                src_batch_df.columns = [c.upper() for c in src_batch_df.columns]
                tgt_batch_df.columns = [c.upper() for c in tgt_batch_df.columns]

                # Index by keys for fast lookup
                if len(src_batch_df) > 0 and len(tgt_batch_df) > 0:
                    src_indexed = src_batch_df.set_index(key_upper)
                    tgt_indexed = tgt_batch_df.set_index(key_upper)
                    common_keys = src_indexed.index.intersection(tgt_indexed.index)

                    for key_val in common_keys:
                        src_row = src_indexed.loc[key_val]
                        tgt_row = tgt_indexed.loc[key_val]
                        if isinstance(src_row, pd.DataFrame):
                            src_row = src_row.iloc[0]
                        if isinstance(tgt_row, pd.DataFrame):
                            tgt_row = tgt_row.iloc[0]
                        diffs = _column_level_diff(src_row, tgt_row, ignore_set)
                        for d in diffs:
                            if isinstance(key_val, tuple):
                                d.update(dict(zip(key_upper, key_val)))
                            else:
                                d[key_upper[0]] = key_val
                        column_details.extend(diffs)

        details = pd.DataFrame(column_details) if column_details else None
        mismatch_cols = ", ".join(sorted({d["column"] for d in column_details})) if column_details else ""

        # Column mismatch distribution
        col_mismatch_summary = ""
        if column_details:
            from collections import Counter
            col_counts = Counter(d["column"] for d in column_details)
            col_mismatch_summary = ", ".join(
                f"{col}:{cnt}" for col, cnt in col_counts.most_common(10)
            )

        # Match percentage
        matched_rows = len(both) - n_hash_diff
        total_compared = max(src_count, tgt_count)
        match_pct = _compute_match_pct(src_count, tgt_count, n_only_src, n_only_tgt, n_hash_diff)

        status = Status.PASS if total_mismatches == 0 else Status.FAIL

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={
                "src_row_count": src_count,
                "tgt_row_count": tgt_count,
                "rows_only_in_source": n_only_src,
                "rows_only_in_target": n_only_tgt,
                "rows_hash_mismatch": n_hash_diff,
                "rows_with_diffs": n_hash_diff,
                "rows_matched": matched_rows,
                "match_pct": match_pct,
                "cell_diffs_found": len(column_details),
                "column_diffs_found": len(column_details),
                "mismatch_columns": mismatch_cols,
                "column_mismatch_summary": col_mismatch_summary,
                "comparison_mode": "keyed",
                "join_keys_used": ", ".join(k.upper() for k in join_keys),
                "strategy": "hash",
            },
            details=details,
            message=(
                f"Hash compare: src={src_count:,}, tgt={tgt_count:,}, "
                f"match={match_pct}%, "
                f"only_src={n_only_src:,}, only_tgt={n_only_tgt:,}, "
                f"hash_diff={n_hash_diff:,}, col_diffs={len(column_details)}"
            ),
        )

    # ── Strategy 2: Deterministic sample ─────────────────────────────────────

    def _sample_strategy(self, src_conn, tgt_conn, config: CheckConfig,
                         sample_pct: float) -> CheckResult:
        """Compare a deterministic subset of rows for fast smoke testing."""
        logger.info("Using SAMPLE strategy (%s%%) for data comparison", sample_pct)

        join_keys = config.join_keys if config.join_keys and config.join_keys != ["NA"] else None
        if not join_keys:
            logger.info("Sample strategy requires join_keys — falling back to full")
            return self._full_strategy(src_conn, tgt_conn, config)

        sample_where = deterministic_sample_where(join_keys[0], sample_pct)
        combined_where = f"{config.where} AND {sample_where}" if config.where else sample_where

        # Run full strategy on the sampled subset
        sampled_config = CheckConfig(
            check_type=config.check_type,
            source_table=config.source_table,
            target_table=config.target_table,
            columns=config.columns,
            join_keys=config.join_keys,
            ignore_columns=config.ignore_columns,
            where=combined_where,
            chunk_size=config.chunk_size,
            extra=config.extra,
        )
        result = self._full_strategy(src_conn, tgt_conn, sampled_config)
        result.metrics["strategy"] = "sample"
        result.metrics["sample_pct"] = sample_pct
        result.message = f"[Sample {sample_pct}%] {result.message}"
        return result

    # ── Strategy 3: Full comparison with streaming ───────────────────────────

    def _full_strategy(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:
        """Full row-level comparison with streaming support for large tables."""
        logger.info("Using FULL strategy for data comparison")

        where = config.where
        src_table = config.source_table
        tgt_table = config.target_table
        join_keys = config.join_keys if config.join_keys and config.join_keys != ["NA"] else None
        chunk_size = config.chunk_size
        max_mismatches = config.extra.get("max_mismatches", 10_000)
        use_streaming = config.extra.get("streaming", False)

        # Get columns
        src_cols = tgt_conn.get_column_names(tgt_table, exclude=config.ignore_columns)
        col_list = ", ".join(f'"{c}"' for c in src_cols)
        clause = f"WHERE {where}" if where else ""
        order_by = f"ORDER BY {', '.join(f'\"' + k + '\"' for k in join_keys)}" if join_keys else ""
        query_src = f"SELECT {col_list} FROM {src_table} {clause} {order_by}"
        query_tgt = f"SELECT {col_list} FROM {tgt_table} {clause} {order_by}"

        if use_streaming:
            return self._streaming_compare(
                src_conn, tgt_conn, query_src, query_tgt,
                join_keys, chunk_size, max_mismatches, src_table, tgt_table,
            )

        # Non-streaming: load into memory
        src_df = src_conn.execute_query(query_src)
        tgt_df = tgt_conn.execute_query(query_tgt)

        src_df.columns = [c.upper() for c in src_df.columns]
        tgt_df.columns = [c.upper() for c in tgt_df.columns]

        # Align dtypes
        try:
            tgt_df = tgt_df.astype(src_df.dtypes)
        except (ValueError, TypeError):
            try:
                src_df = src_df.astype(tgt_df.dtypes)
            except (ValueError, TypeError):
                logger.warning("Could not align dtypes between source and target")

        src_count = len(src_df)
        tgt_count = len(tgt_df)

        # Auto-detect keys if none provided
        if not join_keys:
            join_keys = self._auto_detect_keys_df(src_df, tgt_df)

        # Sort
        if join_keys:
            src_df.sort_values(by=join_keys, inplace=True)
            tgt_df.sort_values(by=join_keys, inplace=True)
        else:
            src_df.sort_values(by=list(src_df.columns), inplace=True)
            tgt_df.sort_values(by=list(tgt_df.columns), inplace=True)

        src_df.reset_index(drop=True, inplace=True)
        tgt_df.reset_index(drop=True, inplace=True)

        # Chunked comparison
        differences_src = []
        differences_tgt = []
        total_rows = max(src_count, tgt_count)
        chunk_start = 0

        while chunk_start < total_rows:
            chunk_end = min(chunk_start + chunk_size, total_rows)
            src_chunk = src_df.iloc[chunk_start:chunk_end].copy()
            tgt_chunk = tgt_df.iloc[chunk_start:chunk_end].copy()

            src_chunk.replace("", None, inplace=True)
            tgt_chunk.replace("", None, inplace=True)

            merged = src_chunk.merge(tgt_chunk, how="outer", indicator=True)
            differences_src.append(merged[merged["_merge"] == "left_only"].drop(columns=["_merge"]))
            differences_tgt.append(merged[merged["_merge"] == "right_only"].drop(columns=["_merge"]))

            chunk_start += chunk_size

            total_diffs = sum(len(d) for d in differences_src) + sum(len(d) for d in differences_tgt)
            if total_diffs >= max_mismatches:
                logger.warning("Max mismatch limit (%d) reached, stopping early", max_mismatches)
                break

        all_src_diffs = pd.concat(differences_src, ignore_index=True) if differences_src else pd.DataFrame()
        all_tgt_diffs = pd.concat(differences_tgt, ignore_index=True) if differences_tgt else pd.DataFrame()

        is_match = len(all_src_diffs) == 0 and len(all_tgt_diffs) == 0
        status = Status.PASS if is_match else Status.FAIL

        total_mismatches = len(all_src_diffs) + len(all_tgt_diffs)
        total_compared = max(src_count, tgt_count)
        rows_with_diffs = max(len(all_src_diffs), len(all_tgt_diffs))
        matched_rows = total_compared - rows_with_diffs
        match_pct = _compute_match_pct(src_count, tgt_count, len(all_src_diffs), len(all_tgt_diffs), 0)

        # Column-level drill-down: pair rows by join key and diff each column
        mismatch_cols = ""
        col_mismatch_summary = ""
        details = None
        keyed = bool(join_keys)
        if join_keys and len(all_src_diffs) > 0 and len(all_tgt_diffs) > 0:
            details, mismatch_cols, col_mismatch_summary = self._column_drill_down(
                all_src_diffs, all_tgt_diffs, join_keys, config.ignore_columns, max_mismatches
            )
        elif not join_keys:
            # No keys — positional column-level drill-down on the sorted data
            ignore_set = {c.upper() for c in config.ignore_columns}
            column_details = []
            min_rows = min(src_count, tgt_count)
            data_cols = [c for c in src_df.columns if c.upper() not in ignore_set]
            for idx in range(min_rows):
                src_row = src_df.iloc[idx]
                tgt_row = tgt_df.iloc[idx]
                for col in data_cols:
                    sv, tv = src_row[col], tgt_row[col]
                    if pd.isna(sv) and pd.isna(tv):
                        continue
                    if not pd.isna(sv) and not pd.isna(tv):
                        try:
                            if float(sv) == float(tv):
                                continue
                        except (ValueError, TypeError):
                            pass
                    if str(sv) != str(tv):
                        column_details.append({
                            "ROW": idx + 1,
                            "column": col,
                            "source_value": str(sv) if not pd.isna(sv) else "NULL",
                            "target_value": str(tv) if not pd.isna(tv) else "NULL",
                        })
                if len(column_details) >= max_mismatches:
                    break

            rows_with_diffs = len({d["ROW"] for d in column_details}) if column_details else 0
            rows_only_src = max(0, src_count - tgt_count)
            rows_only_tgt = max(0, tgt_count - src_count)
            match_pct = _compute_match_pct(src_count, tgt_count, rows_only_src, rows_only_tgt, rows_with_diffs)
            total_mismatches = len(column_details) + rows_only_src + rows_only_tgt
            is_match = total_mismatches == 0
            status = Status.PASS if is_match else Status.FAIL

            from collections import Counter
            col_counts = Counter(d["column"] for d in column_details)
            mismatch_cols = ", ".join(sorted(col_counts.keys()))
            col_mismatch_summary = ", ".join(f"{c}:{n}" for c, n in col_counts.most_common(10))
            details = pd.DataFrame(column_details) if column_details else None

            return CheckResult(
                check_type=self.name,
                status=status,
                metrics={
                    "src_row_count": src_count,
                    "tgt_row_count": tgt_count,
                    "rows_only_in_source": rows_only_src,
                    "rows_only_in_target": rows_only_tgt,
                    "rows_with_diffs": rows_with_diffs,
                    "cell_diffs_found": len(column_details),
                    "rows_matched": matched_rows,
                    "match_pct": match_pct,
                    "mismatch_columns": mismatch_cols,
                    "column_mismatch_summary": col_mismatch_summary,
                    "comparison_mode": "positional",
                    "join_keys_used": "none",
                    "strategy": "full",
                },
                details=details,
                message=(
                    f"Source={src_count:,}, Target={tgt_count:,}, "
                    f"match={match_pct}%, keys=none (positional), "
                    f"rows_with_diffs={rows_with_diffs}, "
                    f"Only-in-src={rows_only_src:,}, Only-in-tgt={rows_only_tgt:,}"
                ),
            )

        return CheckResult(
            check_type=self.name,
            status=status,
            metrics={
                "src_row_count": src_count,
                "tgt_row_count": tgt_count,
                "rows_only_in_source": len(all_src_diffs),
                "rows_only_in_target": len(all_tgt_diffs),
                "rows_matched": matched_rows,
                "match_pct": match_pct,
                "mismatch_columns": mismatch_cols,
                "column_mismatch_summary": col_mismatch_summary,
                "comparison_mode": "keyed" if keyed else "positional",
                "join_keys_used": ", ".join(k.upper() for k in join_keys) if join_keys else "none",
                "strategy": "full",
            },
            details=details,
            message=(
                f"Source={src_count:,}, Target={tgt_count:,}, "
                f"match={match_pct}%, "
                f"Only-in-src={len(all_src_diffs):,}, Only-in-tgt={len(all_tgt_diffs):,}"
            ),
        )

    # ── Streaming comparison (for very large tables) ─────────────────────────

    def _streaming_compare(
        self, src_conn, tgt_conn,
        src_query: str, tgt_query: str,
        join_keys: list[str] | None,
        chunk_size: int, max_mismatches: int,
        src_table: str, tgt_table: str,
    ) -> CheckResult:
        """Compare using server-side cursor streaming — no full load."""
        logger.info("Streaming comparison active")

        differences_src = []
        differences_tgt = []
        src_count = 0
        tgt_count = 0

        src_stream = src_conn.execute_streaming(src_query, chunk_size)
        tgt_stream = tgt_conn.execute_streaming(tgt_query, chunk_size)

        src_exhausted = False
        tgt_exhausted = False

        while not (src_exhausted and tgt_exhausted):
            try:
                src_chunk = next(src_stream)
            except StopIteration:
                src_chunk = pd.DataFrame()
                src_exhausted = True

            try:
                tgt_chunk = next(tgt_stream)
            except StopIteration:
                tgt_chunk = pd.DataFrame()
                tgt_exhausted = True

            if src_chunk.empty and tgt_chunk.empty:
                break

            src_chunk.replace("", None, inplace=True)
            tgt_chunk.replace("", None, inplace=True)

            src_count += len(src_chunk)
            tgt_count += len(tgt_chunk)

            if not src_chunk.empty and not tgt_chunk.empty:
                merged = src_chunk.merge(tgt_chunk, how="outer", indicator=True)
                differences_src.append(merged[merged["_merge"] == "left_only"].drop(columns=["_merge"]))
                differences_tgt.append(merged[merged["_merge"] == "right_only"].drop(columns=["_merge"]))
            elif not src_chunk.empty:
                differences_src.append(src_chunk)
            elif not tgt_chunk.empty:
                differences_tgt.append(tgt_chunk)

            total_diffs = sum(len(d) for d in differences_src) + sum(len(d) for d in differences_tgt)
            if total_diffs >= max_mismatches:
                logger.warning("Max mismatch limit reached in streaming mode")
                break

        all_src_diffs = pd.concat(differences_src, ignore_index=True) if differences_src else pd.DataFrame()
        all_tgt_diffs = pd.concat(differences_tgt, ignore_index=True) if differences_tgt else pd.DataFrame()

        is_match = len(all_src_diffs) == 0 and len(all_tgt_diffs) == 0

        total_compared = max(src_count, tgt_count)
        matched_rows = total_compared - max(len(all_src_diffs), len(all_tgt_diffs))
        match_pct = _compute_match_pct(src_count, tgt_count, len(all_src_diffs), len(all_tgt_diffs), 0)

        # Column-level drill-down when join keys are available
        key_list = join_keys if join_keys else []
        if key_list and len(all_src_diffs) > 0 and len(all_tgt_diffs) > 0:
            details, mismatch_cols, col_mismatch_summary = self._column_drill_down(
                all_src_diffs, all_tgt_diffs, key_list, [], max_mismatches
            )
        else:
            details = self._build_details(all_src_diffs, all_tgt_diffs, max_mismatches)
            mismatch_cols = ""
            col_mismatch_summary = ""

        return CheckResult(
            check_type=self.name,
            status=Status.PASS if is_match else Status.FAIL,
            metrics={
                "src_row_count": src_count,
                "tgt_row_count": tgt_count,
                "rows_only_in_source": len(all_src_diffs),
                "rows_only_in_target": len(all_tgt_diffs),
                "rows_matched": matched_rows,
                "match_pct": match_pct,
                "mismatch_columns": mismatch_cols,
                "column_mismatch_summary": col_mismatch_summary,
                "comparison_mode": "keyed" if join_keys else "positional",
                "join_keys_used": ", ".join(k.upper() for k in join_keys) if join_keys else "none",
                "strategy": "streaming",
            },
            details=details,
            message=(
                f"Streaming: src={src_count:,}, tgt={tgt_count:,}, "
                f"match={match_pct}%, "
                f"only_src={len(all_src_diffs):,}, only_tgt={len(all_tgt_diffs):,}"
            ),
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _column_drill_down(
        src_diffs: pd.DataFrame, tgt_diffs: pd.DataFrame,
        join_keys: list[str], ignore_columns: list[str],
        max_rows: int,
    ) -> tuple[pd.DataFrame | None, str, str]:
        """Pair mismatched rows by join key, then diff each column to produce
        a details table of (join_keys, column, source_value, target_value).

        Returns: (details_df, mismatch_columns_str, column_mismatch_summary_str)
        """
        from collections import Counter

        key_upper = [k.upper() for k in join_keys]
        ignore_set = {c.upper() for c in ignore_columns}
        ignore_set.update({"_SIDE", "_MERGE"})

        # Merge src and tgt diffs on keys to pair matching rows
        merged = src_diffs.merge(
            tgt_diffs, on=key_upper, how="inner",
            suffixes=("_SRC", "_TGT"),
        )

        column_details = []
        # Identify the data columns (not keys, not internal)
        data_cols = []
        for c in src_diffs.columns:
            if c not in key_upper and c.upper() not in ignore_set:
                data_cols.append(c)

        for _, row in merged.head(max_rows).iterrows():
            for col in data_cols:
                src_col = f"{col}_SRC" if f"{col}_SRC" in row.index else col
                tgt_col = f"{col}_TGT" if f"{col}_TGT" in row.index else col
                sv = row.get(src_col)
                tv = row.get(tgt_col)
                if str(sv) != str(tv):
                    entry = {"column": col, "source_value": sv, "target_value": tv}
                    entry.update({k: row[k] for k in key_upper if k in row.index})
                    column_details.append(entry)

        # Also capture rows only on one side (no pair to diff)
        only_src_keys = set()
        only_tgt_keys = set()
        if len(key_upper) == 1:
            k = key_upper[0]
            paired_keys = set(merged[k].tolist()) if len(merged) > 0 else set()
            only_src_keys = set(src_diffs[k].tolist()) - paired_keys
            only_tgt_keys = set(tgt_diffs[k].tolist()) - paired_keys

        # Build combined details
        if column_details:
            details_df = pd.DataFrame(column_details)
            col_counts = Counter(d["column"] for d in column_details)
            mismatch_cols = ", ".join(sorted(col_counts.keys()))
            col_mismatch_summary = ", ".join(
                f"{col}:{cnt}" for col, cnt in col_counts.most_common(10)
            )
        else:
            details_df = None
            mismatch_cols = ""
            col_mismatch_summary = ""

        # Append unpaired rows (only-in-source / only-in-target) as context
        if details_df is None and (len(src_diffs) > 0 or len(tgt_diffs) > 0):
            # No paired rows found — fallback to the old side-tagged format
            parts = []
            if len(src_diffs) > 0:
                sd = src_diffs.head(max_rows).copy()
                sd["_side"] = "only_in_source"
                parts.append(sd)
            if len(tgt_diffs) > 0:
                td = tgt_diffs.head(max_rows).copy()
                td["_side"] = "only_in_target"
                parts.append(td)
            details_df = pd.concat(parts, ignore_index=True) if parts else None

        return details_df, mismatch_cols, col_mismatch_summary

    @staticmethod
    def _build_details(src_diffs: pd.DataFrame, tgt_diffs: pd.DataFrame,
                       max_rows: int) -> pd.DataFrame | None:
        parts = []
        if len(src_diffs) > 0:
            sd = src_diffs.head(max_rows).copy()
            sd["_side"] = "only_in_source"
            parts.append(sd)
        if len(tgt_diffs) > 0:
            td = tgt_diffs.head(max_rows).copy()
            td["_side"] = "only_in_target"
            parts.append(td)
        return pd.concat(parts, ignore_index=True) if parts else None
