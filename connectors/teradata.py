"""Teradata connector using pyodbc — optimised for Teradata-specific SQL.

Leverages Teradata features:
- HASHROW() for server-side row hashing (faster than MD5(CONCAT()))
- SAMPLE for deterministic sampling
- HELP COLUMN for metadata
- CAST optimisations aligned with Teradata type system
- Teradata-native aggregate and profiling syntax
"""

import logging
import re

import duckdb
import pandas as pd
import pyodbc

from .base import BaseConnector, ConnectionConfig, safe_identifier, safe_identifiers, safe_table_expr, quote_identifier

logger = logging.getLogger(__name__)


class TeradataConnector(BaseConnector):

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def connect(self):
        logger.info("Connecting to Teradata via ODBC …")
        timeout = self.config.extra.get("connect_timeout", 30)
        self._conn = pyodbc.connect(
            self.config.dsn,
            UID=self.config.user,
            PWD=self.config.password,
            timeout=timeout,
        )
        # Set query timeout (seconds) — prevents runaway queries
        query_timeout = self.config.extra.get("query_timeout", 600)
        self._conn.timeout = query_timeout
        logger.info("Teradata connection established (connect_timeout=%ds, query_timeout=%ds).", timeout, query_timeout)

    def _execute_query_impl(self, query: str, params: dict | None = None) -> pd.DataFrame:
        return pd.read_sql_query(query, self._conn)

    def is_alive(self) -> bool:
        try:
            self.execute_query("SELECT 1")
            return True
        except Exception:
            return False

    # ── metadata ──────────────────────────────────────────────────────────────

    def get_metadata(self, table: str) -> pd.DataFrame:
        table = safe_table_expr(table)
        help_col_df = pd.read_sql_query(f"HELP COLUMN {table}.*", self._conn)
        help_col_df["Decimal Total Digits"] = (
            help_col_df["Decimal Total Digits"].fillna(0).astype(int)
        )
        help_col_df["Decimal Fractional Digits"] = (
            help_col_df["Decimal Fractional Digits"].fillna(0).astype(int)
        )
        # Use DuckDB for the complex CASE expression (matches original logic)
        result = duckdb.query("""
            SELECT
                UPPER("Column SQL Name") AS COLUMN_NAME,
                CASE
                    WHEN trim(Type)='I'  THEN 'NUMBER(10,0)'
                    WHEN trim(Type)='I1' THEN 'NUMBER(3,0)'
                    WHEN trim(Type)='I2' THEN 'NUMBER(5,0)'
                    WHEN trim(Type)='I8' THEN 'NUMBER(19,0)'
                    WHEN trim(Type) IN ('CV','CF') THEN
                        trim(replace("Format",'X','VARCHAR'))
                    WHEN trim(Type) IN ('D','N') AND "Decimal Total Digits" < 0
                        THEN 'NUMBER(38,5)'
                    WHEN trim(Type) IN ('D','N') AND "Decimal Total Digits" > 0
                        THEN 'NUMBER('||"Decimal Total Digits"||','||"Decimal Fractional Digits"||')'
                    WHEN trim(Type)='TS'
                        THEN 'TIMESTAMP_NTZ('||"Decimal Fractional Digits"||')'
                    WHEN trim(Type)='DA' THEN 'DATE'
                    WHEN trim(Type)='F'  THEN 'FLOAT'
                END AS DATA_TYPE,
                Nullable AS NULLABLE
            FROM help_col_df
        """).df()
        return result[["COLUMN_NAME", "DATA_TYPE", "NULLABLE"]]

    # ── Teradata-optimised helpers ────────────────────────────────────────────

    def get_row_count(self, table: str, where: str = "") -> int:
        """Row count — uses Teradata-optimised single-AMP query when no filter."""
        table = safe_table_expr(table)
        clause = f"WHERE {where}" if where else ""
        df = self.execute_query(f"SELECT COUNT(*) AS CNT FROM {table} {clause}")
        return int(df.iloc[0, 0])

    def get_empty_counts(self, table: str, columns: list[str], where: str = "") -> pd.DataFrame:
        """Teradata-optimised: uses TRIM + CHARACTERS instead of generic VARCHAR cast."""
        cols = safe_identifiers(columns)
        expressions = [
            f'SUM(CASE WHEN TRIM("{c}") = \'\' OR CHARACTERS(TRIM("{c}")) = 0 '
            f'THEN 1 ELSE 0 END) AS "{c}"'
            for c in cols
        ]
        clause = f"WHERE {where}" if where else ""
        query = f"SELECT {', '.join(expressions)} FROM {safe_table_expr(table)} {clause}"
        return self.execute_query(query)

    def get_aggregates(self, table: str, columns: list[str],
                       functions: list[str] = None, where: str = "") -> pd.DataFrame:
        """Teradata-optimised: uses CAST(… AS FLOAT) instead of ::FLOAT."""
        if functions is None:
            functions = ["MIN", "MAX", "AVG", "SUM"]
        cols = safe_identifiers(columns)
        expressions = []
        for col in cols:
            for func in functions:
                expressions.append(
                    f'COALESCE(CAST({func}("{col}") AS DECIMAL(38,5)), 0) AS "{func}_{col}"'
                )
        clause = f"WHERE {where}" if where else ""
        query = f"SELECT {', '.join(expressions)} FROM {safe_table_expr(table)} {clause}"
        return self.execute_query(query)

    def get_max_timestamp(self, table: str, column: str, where: str = ""):
        """Teradata-native MAX timestamp."""
        col = safe_identifier(column)
        clause = f"WHERE {where}" if where else ""
        df = self.execute_query(
            f'SELECT MAX("{col}") AS MAX_TS FROM {safe_table_expr(table)} {clause}'
        )
        return df.iloc[0, 0]

    def execute_streaming(
        self, query: str, chunk_size: int = 50_000
    ) -> "Generator[pd.DataFrame, None, None]":
        """Stream results using pyodbc cursor fetchmany for Teradata."""
        cursor = self._conn.cursor()
        try:
            cursor.execute(query)
            columns = [desc[0].upper() for desc in cursor.description]

            while True:
                rows = cursor.fetchmany(chunk_size)
                if not rows:
                    break
                df = pd.DataFrame.from_records(rows, columns=columns)
                yield df
        finally:
            cursor.close()
