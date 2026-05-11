"""YAML test-suite loader."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..checks.base import CheckConfig
from ..connectors.base import ConnectionConfig

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')


def _expand_env_vars(value):
    """Recursively expand ${VAR} references in strings, dicts, and lists."""
    if isinstance(value, str):
        return _ENV_VAR_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


@dataclass
class TestSuite:
    """Represents a complete test suite loaded from YAML."""
    name: str
    source: ConnectionConfig
    target: ConnectionConfig
    checks: list[CheckConfig] = field(default_factory=list)
    source_platform: str = ""
    target_platform: str = ""
    source_table: str = ""
    target_table: str = ""
    global_where: str = ""


def _parse_connection(block: dict, connections_map: dict) -> tuple[str, ConnectionConfig]:
    """Parse a source/target block into (platform, ConnectionConfig)."""
    platform = block.get("platform", "teradata")
    conn_ref = block.get("connection")

    if conn_ref and conn_ref in connections_map:
        conn_data = connections_map[conn_ref]
    else:
        conn_data = block

    return platform, ConnectionConfig(
        platform=platform,
        dsn=conn_data.get("dsn", ""),
        host=conn_data.get("host", ""),
        port=conn_data.get("port", 0),
        user=conn_data.get("user", ""),
        password=conn_data.get("password", ""),
        database=conn_data.get("database", ""),
        schema=conn_data.get("schema", ""),
        catalog=conn_data.get("catalog", ""),
        extra=conn_data.get("extra", {}),
    )


def _parse_check(check_dict: dict, source_table: str, target_table: str,
                  global_where: str) -> CheckConfig:
    """Parse one check entry from the YAML."""
    check_type = check_dict["type"]
    where = check_dict.get("where", global_where)

    # Handle "columns" which might be a list or string
    columns = check_dict.get("columns", [])
    if isinstance(columns, str):
        columns = [c.strip() for c in columns.split(",") if c.strip()]

    join_keys = check_dict.get("join_keys", check_dict.get("keys", []))
    if isinstance(join_keys, str):
        join_keys = [k.strip() for k in join_keys.split(",") if k.strip()]

    ignore = check_dict.get("ignore_columns", ["DL_INSERT_TS", "DL_UPDATE_TS"])
    if isinstance(ignore, str):
        ignore = [c.strip() for c in ignore.split(",") if c.strip()]

    functions = check_dict.get("functions", ["MIN", "MAX", "AVG", "SUM"])
    if isinstance(functions, str):
        functions = [f.strip().upper() for f in functions.split(",") if f.strip()]

    # Extra fields
    # Fields that should remain as scalars (not split into lists)
    _scalar_extras = {"strategy", "sample_pct", "column_drill_down", "streaming", "max_mismatches"}
    # Fields that are comma-separated lists
    _list_extras = {"id_columns", "numeric_columns"}

    extra = {}
    for key in (*_list_extras, *_scalar_extras):
        if key in check_dict:
            val = check_dict[key]
            if key in _list_extras and isinstance(val, str):
                val = [v.strip() for v in val.split(",") if v.strip()]
            extra[key] = val

    return CheckConfig(
        check_type=check_type,
        source_table=check_dict.get("source_table", source_table),
        target_table=check_dict.get("target_table", target_table),
        columns=columns,
        join_keys=join_keys,
        ignore_columns=ignore,
        where=where,
        chunk_size=check_dict.get("chunk_size", 50_000),
        tolerance=check_dict.get("tolerance", 0),
        functions=functions,
        extra=extra,
    )


def load_suite(path: str | Path, connections_file: str | Path | None = None) -> TestSuite:
    """Load a test suite from a YAML file.

    Parameters
    ----------
    path : path to the suite YAML file
    connections_file : optional path to a shared connections YAML file
    """
    path = Path(path)
    logger.info("Loading test suite from %s", path)

    with open(path) as f:
        data = yaml.safe_load(f)
    data = _expand_env_vars(data)

    connections_map = {}
    if connections_file:
        with open(connections_file) as f:
            raw = yaml.safe_load(f)
        raw = _expand_env_vars(raw)
        connections_map = raw.get("connections", {})

    suite_name = data.get("test_suite", path.stem)

    src_platform, src_conn = _parse_connection(data.get("source", {}), connections_map)
    tgt_platform, tgt_conn = _parse_connection(data.get("target", {}), connections_map)

    source_table = data.get("source", {}).get("table", "")
    target_table = data.get("target", {}).get("table", "")
    global_where = data.get("filters", {}).get("where", "")

    checks = []
    for check_dict in data.get("checks", []):
        checks.append(_parse_check(check_dict, source_table, target_table, global_where))

    suite = TestSuite(
        name=suite_name,
        source=src_conn,
        target=tgt_conn,
        checks=checks,
        source_platform=src_platform,
        target_platform=tgt_platform,
        source_table=source_table,
        target_table=target_table,
        global_where=global_where,
    )
    logger.info("Suite '%s' loaded with %d check(s)", suite.name, len(suite.checks))
    return suite


def load_suites_from_dir(directory: str | Path, connections_file: str | Path | None = None) -> list[TestSuite]:
    """Load all .yaml / .yml test suites from a directory."""
    directory = Path(directory)
    suites = []
    for p in sorted(directory.glob("*.y*ml")):
        if p.name.startswith("_") or "connection" in p.name.lower():
            continue
        try:
            suites.append(load_suite(p, connections_file))
        except Exception as e:
            logger.error("Failed to load suite %s: %s", p, e)
    return suites
