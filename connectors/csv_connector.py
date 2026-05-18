"""CSV file connector — treats a CSV file like a table."""

import logging

import pandas as pd

from .base import BaseConnector, ConnectionConfig

logger = logging.getLogger(__name__)


class CSVConnector(BaseConnector):
    """Reads data from a local CSV file.

    ``config.extra["file_path"]`` must point to the CSV file.
    Caches the DataFrame after first read to avoid re-parsing.
    """

    def connect(self):
        self._file_path = self.config.extra.get("file_path", "")
        if not self._file_path:
            raise ValueError("CSVConnector requires extra.file_path")
        self._df_cache: pd.DataFrame | None = None
        logger.info("CSV connector initialised for %s", self._file_path)

    def _execute_query_impl(self, query: str, params: dict | None = None) -> pd.DataFrame:
        raise NotImplementedError(
            "CSVConnector does not support raw SQL. Use helper methods."
        )

    def read_dataframe(self) -> pd.DataFrame:
        """Read CSV with caching — file is only parsed once.

        Tries UTF-8 first, falls back to latin-1 (which accepts any byte).
        """
        if self._df_cache is None:
            try:
                self._df_cache = pd.read_csv(self._file_path, header=0, encoding="utf-8")
            except UnicodeDecodeError:
                logger.warning("UTF-8 decode failed for %s — retrying with latin-1 encoding",
                               self._file_path)
                self._df_cache = pd.read_csv(self._file_path, header=0, encoding="latin-1")
            logger.info("CSV loaded: %d rows, %d columns", len(self._df_cache), len(self._df_cache.columns))
        return self._df_cache.copy()

    def _apply_where(self, df: pd.DataFrame, where: str) -> pd.DataFrame:
        """Safely apply a WHERE-like filter using pandas query.

        Validates the expression doesn't contain dangerous constructs.
        """
        if not where:
            return df
        # Block common injection patterns
        blocked = ("__", "import", "exec", "eval", "compile", "open", "system", "os.", "sys.")
        where_lower = where.lower()
        for pattern in blocked:
            if pattern in where_lower:
                raise ValueError(f"Blocked expression in WHERE clause: {where!r}")
        return df.query(where)

    def is_alive(self) -> bool:
        """CSV connector is alive if the file path is set."""
        return bool(self._file_path)

    def get_metadata(self, table: str) -> pd.DataFrame:
        df = self.read_dataframe()
        rows = []
        for col in df.columns:
            rows.append({
                "COLUMN_NAME": col.upper(),
                "DATA_TYPE": str(df[col].dtype),
                "NULLABLE": "Y",
            })
        return pd.DataFrame(rows)

    def get_row_count(self, table: str, where: str = "") -> int:
        df = self.read_dataframe()
        if where:
            df = self._apply_where(df, where)
        return len(df)

    def get_null_counts(self, table: str, columns: list[str], where: str = "") -> pd.DataFrame:
        df = self.read_dataframe()
        if where:
            df = self._apply_where(df, where)
        result = {}
        for col in columns:
            matching = [c for c in df.columns if c.upper() == col.upper()]
            if matching:
                result[col.upper()] = int(df[matching[0]].isna().sum())
            else:
                result[col.upper()] = 0
        return pd.DataFrame([result])

    def get_empty_counts(self, table: str, columns: list[str], where: str = "") -> pd.DataFrame:
        df = self.read_dataframe()
        if where:
            df = self._apply_where(df, where)
        result = {}
        for col in columns:
            matching = [c for c in df.columns if c.upper() == col.upper()]
            if matching:
                series = df[matching[0]]
                result[col.upper()] = int(
                    series.fillna("").astype(str).str.strip().eq("").sum()
                    - series.isna().sum()  # exclude NaN from empty count
                )
            else:
                result[col.upper()] = 0
        return pd.DataFrame([result])

    def get_duplicates(self, table: str, columns: list[str], where: str = "") -> pd.DataFrame:
        df = self.read_dataframe()
        if where:
            df = self._apply_where(df, where)
        col_map = []
        for col in columns:
            matching = [c for c in df.columns if c.upper() == col.upper()]
            if matching:
                col_map.append(matching[0])
        dupes = df[df.duplicated(subset=col_map, keep=False)]
        return dupes[col_map].drop_duplicates()

    def get_aggregates(self, table: str, columns: list[str],
                       functions: list[str] = None, where: str = "") -> pd.DataFrame:
        if functions is None:
            functions = ["MIN", "MAX", "AVG", "SUM"]
        df = self.read_dataframe()
        if where:
            df = self._apply_where(df, where)
        result = {}
        func_map = {"MIN": "min", "MAX": "max", "AVG": "mean", "SUM": "sum"}
        for col in columns:
            matching = [c for c in df.columns if c.upper() == col.upper()]
            if not matching:
                continue
            series = pd.to_numeric(df[matching[0]], errors="coerce")
            for func in functions:
                val = getattr(series, func_map[func])()
                result[f"{func}_{col.upper()}"] = round(val, 5) if pd.notna(val) else 0
        return pd.DataFrame([result])

    def get_column_names(self, table: str, exclude: list[str] | None = None) -> list[str]:
        """Get column names from CSV without going through metadata/DuckDB."""
        df = self.read_dataframe()
        cols = [c.upper() for c in df.columns]
        if exclude:
            exclude_upper = {c.upper() for c in exclude}
            cols = [c for c in cols if c not in exclude_upper]
        return cols

    def close(self):
        self._df_cache = None
