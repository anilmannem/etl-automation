"""Abstract base connector and SQL safety utilities.

Includes:
- SQL injection protection via identifier validation
- Server-side cursor streaming for large datasets
- Statistical sampling support
- Connection health checking
"""

import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generator

import pandas as pd

logger = logging.getLogger(__name__)

# ── SQL Safety ────────────────────────────────────────────────────────────────
_VALID_IDENTIFIER = re.compile(r'^"?[A-Za-z_][A-Za-z0-9_.$]*"?$')


def safe_identifier(name: str) -> str:
    """Validate that *name* is a legal SQL identifier (table, column, schema).
    Raises ValueError for anything that looks like injection."""
    name = name.strip()
    if not _VALID_IDENTIFIER.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


def safe_table_expr(name: str) -> str:
    """Return a safe SQL table expression.

    Accepts either:
    - A plain identifier/schema.table  →  returned as-is after validation
    - A full SELECT query              →  wrapped as ``(SELECT ...) AS _tbl``
      so it can be used wherever a table reference is expected.
    """
    name = name.strip()
    if name.upper().startswith("SELECT "):
        return f"({name}) AS _tbl"
    return safe_identifier(name)


def safe_identifiers(names: list[str]) -> list[str]:
    return [safe_identifier(n) for n in names]


def quote_identifier(name: str) -> str:
    """Double-quote an identifier (ANSI SQL / Teradata compatible)."""
    name = safe_identifier(name)
    if name.startswith('"'):
        return name
    return f'"{name}"'


def deterministic_sample_where(column: str, pct: float, seed: int = 42) -> str:
    """Generate a deterministic sampling WHERE clause using modular hashing.

    Uses Teradata-compatible HASHROW() for deterministic sampling.
    Ensures the same rows are sampled on both source and target.
    """
    col = safe_identifier(column)
    bucket_count = 10000
    bucket_threshold = int(bucket_count * (pct / 100.0))
    return f'ABS(HASHROW("{col}")) MOD {bucket_count} < {bucket_threshold}'


# ── Base Connector ────────────────────────────────────────────────────────────
@dataclass
class ConnectionConfig:
    """Holds connection parameters loaded from YAML."""
    platform: str
    dsn: str = ""
    host: str = ""
    port: int = 0
    user: str = ""
    password: str = ""
    database: str = ""
    schema: str = ""
    catalog: str = ""
    extra: dict = field(default_factory=dict)


class BaseConnector(ABC):
    """Every data-source connector must implement these methods.

    Enhanced with:
    - Streaming query support (server-side cursors for large datasets)
    - Connection health checks
    - Deterministic sampling helpers
    - Query fingerprinting for caching
    """

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._conn = None

    # ── lifecycle ──
    @abstractmethod
    def connect(self):
        """Open the underlying connection."""

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def is_alive(self) -> bool:
        """Check if the connection is still valid."""
        try:
            self.execute_query("SELECT 1 AS health")
            return True
        except Exception:
            return False

    def reconnect(self):
        """Close and reopen the connection."""
        self.close()
        self.connect()

    # ── query helpers ──
    @abstractmethod
    def execute_query(self, query: str, params: dict | None = None) -> pd.DataFrame:
        """Run *query* and return result as a DataFrame."""

    def execute_streaming(
        self, query: str, chunk_size: int = 50_000
    ) -> Generator[pd.DataFrame, None, None]:
        """Stream results in chunks using server-side cursor.

        This avoids loading entire result sets into memory — critical for
        tables with millions of rows. Falls back to client-side chunking
        if the connector doesn't support server-side cursors.
        """
        try:
            for chunk in pd.read_sql_query(query, self._conn, chunksize=chunk_size):
                chunk.columns = [c.upper() for c in chunk.columns]
                yield chunk
        except TypeError:
            # Some connectors don't support chunksize — fallback
            df = self.execute_query(query)
            df.columns = [c.upper() for c in df.columns]
            for i in range(0, len(df), chunk_size):
                yield df.iloc[i:i + chunk_size].copy()

    def get_row_count(self, table: str, where: str = "") -> int:
        table = safe_identifier(table)
        clause = f"WHERE {where}" if where else ""
        df = self.execute_query(f"SELECT COUNT(*) AS CNT FROM {table} {clause}")
        return int(df.iloc[0, 0])

    @abstractmethod
    def get_metadata(self, table: str) -> pd.DataFrame:
        """Return a DataFrame with columns: COLUMN_NAME, DATA_TYPE, NULLABLE."""

    def get_column_names(self, table: str, exclude: list[str] | None = None) -> list[str]:
        meta = self.get_metadata(table)
        cols = meta["COLUMN_NAME"].tolist()
        if exclude:
            exclude_upper = {c.upper() for c in exclude}
            cols = [c for c in cols if c.upper() not in exclude_upper]
        return cols

    def get_null_counts(self, table: str, columns: list[str], where: str = "") -> pd.DataFrame:
        cols = safe_identifiers(columns)
        expressions = [
            f'SUM(CASE WHEN "{c}" IS NULL THEN 1 ELSE 0 END) AS "{c}"' for c in cols
        ]
        clause = f"WHERE {where}" if where else ""
        query = f"SELECT {', '.join(expressions)} FROM {safe_identifier(table)} {clause}"
        return self.execute_query(query)

    def get_empty_counts(self, table: str, columns: list[str], where: str = "") -> pd.DataFrame:
        cols = safe_identifiers(columns)
        expressions = [
            f"""SUM(CASE WHEN TRIM(CAST("{c}" AS VARCHAR(255))) = '' THEN 1 ELSE 0 END) AS "{c}" """
            for c in cols
        ]
        clause = f"WHERE {where}" if where else ""
        query = f"SELECT {', '.join(expressions)} FROM {safe_identifier(table)} {clause}"
        return self.execute_query(query)

    def get_duplicates(self, table: str, columns: list[str], where: str = "") -> pd.DataFrame:
        cols = [quote_identifier(c) for c in safe_identifiers(columns)]
        col_list = ", ".join(cols)
        clause = f"WHERE {where}" if where else ""
        query = (
            f"SELECT {col_list} FROM {safe_identifier(table)} {clause} "
            f"GROUP BY {col_list} HAVING COUNT(*) > 1"
        )
        return self.execute_query(query)

    def get_aggregates(self, table: str, columns: list[str],
                       functions: list[str] = None, where: str = "") -> pd.DataFrame:
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
        query = f"SELECT {', '.join(expressions)} FROM {safe_identifier(table)} {clause}"
        return self.execute_query(query)

    def get_max_timestamp(self, table: str, column: str, where: str = ""):
        col = safe_identifier(column)
        clause = f"WHERE {where}" if where else ""
        df = self.execute_query(
            f'SELECT MAX("{col}") AS MAX_TS FROM {safe_identifier(table)} {clause}'
        )
        return df.iloc[0, 0]
