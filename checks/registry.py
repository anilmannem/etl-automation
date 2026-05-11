"""Check registry — maps check-type names to check classes.

Migration-focused checks only:
- row_count, metadata, null_check, duplicate, data, aggregate
"""

from .row_count import RowCountCheck
from .metadata import MetadataCheck
from .null_empty import NullCheck
from .duplicate import DuplicateCheck
from .data_compare import DataCheck
from .aggregate import AggregateCheck
from .base import BaseCheck

CHECK_REGISTRY: dict[str, type[BaseCheck]] = {
    "row_count": RowCountCheck,
    "metadata": MetadataCheck,
    "null_check": NullCheck,
    "duplicate": DuplicateCheck,
    "data": DataCheck,
    "aggregate": AggregateCheck,
}


def get_check(check_type: str) -> BaseCheck:
    """Instantiate a check by its registered name."""
    cls = CHECK_REGISTRY.get(check_type)
    if cls is None:
        raise ValueError(
            f"Unknown check type: {check_type!r}. "
            f"Available: {', '.join(sorted(CHECK_REGISTRY))}"
        )
    return cls()
