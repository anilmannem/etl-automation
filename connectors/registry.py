"""Connector registry — maps platform names to connector classes.

Supported platforms:
- teradata / td: Teradata via pyodbc (primary)
- csv / file: local file comparison via pandas
"""

from .base import BaseConnector, ConnectionConfig


def get_connector(platform: str, config: ConnectionConfig) -> BaseConnector:
    """Instantiate the correct connector for *platform*."""
    platform = platform.lower().strip()

    if platform in ("td", "teradata"):
        from .teradata import TeradataConnector
        return TeradataConnector(config)
    elif platform in ("csv", "file"):
        from .csv_connector import CSVConnector
        return CSVConnector(config)
    else:
        raise ValueError(
            f"Unsupported platform: {platform!r}. "
            f"Supported: teradata, td, csv, file"
        )
