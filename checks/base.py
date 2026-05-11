"""Base check class and CheckResult dataclass."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd

logger = logging.getLogger(__name__)


class Status(str, Enum):
    PASS = "Pass"
    FAIL = "Fail"
    WARNING = "Warning"
    ERROR = "Error"
    NOT_APPLICABLE = "Not Applicable"

    def __str__(self):
        return self.value


@dataclass
class CheckResult:
    """Uniform result object returned by every check."""
    check_type: str
    status: Status
    metrics: dict = field(default_factory=dict)
    details: pd.DataFrame | None = None
    message: str = ""

    def to_dict(self) -> dict:
        d = {
            "check_type": self.check_type,
            "status": str(self.status),
            "message": self.message,
        }
        d.update(self.metrics)
        # Include top N detail rows for serialization (JSON, SQLite)
        if self.details is not None and len(self.details) > 0:
            d["details_preview"] = self.details.head(50).to_dict(orient="records")
            d["details_total_rows"] = len(self.details)
        return d


@dataclass
class CheckConfig:
    """Parsed configuration for a single check, from the YAML suite."""
    check_type: str
    source_table: str = ""
    target_table: str = ""
    columns: list[str] = field(default_factory=list)
    join_keys: list[str] = field(default_factory=list)
    ignore_columns: list[str] = field(default_factory=lambda: ["DL_INSERT_TS", "DL_UPDATE_TS"])
    where: str = ""
    chunk_size: int = 50_000
    tolerance: int | float = 0
    functions: list[str] = field(default_factory=lambda: ["MIN", "MAX", "AVG", "SUM"])
    extra: dict = field(default_factory=dict)


class BaseCheck(ABC):
    """All checks inherit from this."""

    name: str = "base"

    @abstractmethod
    def run(self, src_conn, tgt_conn, config: CheckConfig) -> CheckResult:
        """Execute the check and return a CheckResult."""
