"""SQLite connector — lightweight local DB for testing DB↔DB flows."""

import logging
import sqlite3

import pandas as pd

from .base import BaseConnector, ConnectionConfig, safe_identifier

logger = logging.getLogger(__name__)


class SQLiteConnector(BaseConnector):
    """Connects to a SQLite database file (or :memory:).

    ConnectionConfig usage:
        platform: "sqlite"
        database: "/path/to/file.db" or ":memory:"
    """

    def connect(self):
        db_path = self.config.database or ":memory:"
        logger.info("Connecting to SQLite: %s", db_path)
        self._conn = sqlite3.connect(db_path)

    def _execute_query_impl(self, query: str, params: dict | None = None) -> pd.DataFrame:
        return pd.read_sql_query(query, self._conn, params=params)

    def get_metadata(self, table: str) -> pd.DataFrame:
        table = safe_identifier(table)
        cursor = self._conn.execute(f"PRAGMA table_info({table})")
        rows = cursor.fetchall()
        # PRAGMA table_info returns: cid, name, type, notnull, dflt_value, pk
        data = []
        for row in rows:
            data.append({
                "COLUMN_NAME": row[1].upper(),
                "DATA_TYPE": row[2] or "TEXT",
                "NULLABLE": "N" if row[3] else "Y",
            })
        return pd.DataFrame(data)
