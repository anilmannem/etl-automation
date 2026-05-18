"""Test DB↔DB data diff using SQLite (no external DB needed).

Creates two SQLite databases with known differences, then runs:
- data diff (with fingerprint → full strategy fallback)
- duplicate check
- aggregation check

Run: python3 tests/test_db_diff.py
"""
import sys
import os
import sqlite3
import tempfile
import logging

# Ensure the project is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etl_validator.connectors.base import ConnectionConfig
from etl_validator.connectors.registry import get_connector
from etl_validator.checks.registry import get_check
from etl_validator.checks.base import CheckConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

def create_test_dbs():
    """Create source and target SQLite DBs with known differences."""
    src_path = os.path.join(tempfile.gettempdir(), "etl_test_source.db")
    tgt_path = os.path.join(tempfile.gettempdir(), "etl_test_target.db")

    # Source DB
    conn = sqlite3.connect(src_path)
    conn.execute("DROP TABLE IF EXISTS orders")
    conn.execute("""
        CREATE TABLE orders (
            ORDER_ID INTEGER PRIMARY KEY,
            CUSTOMER_ID INTEGER,
            AMOUNT REAL,
            STATUS TEXT,
            ORDER_DATE TEXT
        )
    """)
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", [
        (1, 100, 250.00, "SHIPPED", "2024-01-01"),
        (2, 101, 150.50, "PENDING", "2024-01-02"),
        (3, 102, 320.75, "SHIPPED", "2024-01-03"),
        (4, 103, 99.99,  "DELIVERED", "2024-01-04"),
        (5, 104, 450.00, "SHIPPED", "2024-01-05"),
        (6, 105, 175.25, "PENDING", "2024-01-06"),
        (7, 106, 600.00, "DELIVERED", "2024-01-07"),
        (8, 107, 85.50,  "SHIPPED", "2024-01-08"),
        (9, 108, 220.00, "PENDING", "2024-01-09"),
        (10, 109, 310.00, "DELIVERED", "2024-01-10"),
    ])
    conn.commit()
    conn.close()

    # Target DB — introduce differences:
    # - Row 3: AMOUNT changed (320.75 → 321.00) and STATUS changed
    # - Row 7: missing (deleted)
    # - Row 11: extra row (inserted)
    # - Row 4: duplicate (same ORDER_ID appears twice)
    conn = sqlite3.connect(tgt_path)
    conn.execute("DROP TABLE IF EXISTS orders")
    conn.execute("""
        CREATE TABLE orders (
            ORDER_ID INTEGER,
            CUSTOMER_ID INTEGER,
            AMOUNT REAL,
            STATUS TEXT,
            ORDER_DATE TEXT
        )
    """)
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", [
        (1, 100, 250.00, "SHIPPED", "2024-01-01"),
        (2, 101, 150.50, "PENDING", "2024-01-02"),
        (3, 102, 321.00, "DELIVERED", "2024-01-03"),   # AMOUNT + STATUS changed
        (4, 103, 99.99,  "DELIVERED", "2024-01-04"),
        (4, 103, 99.99,  "DELIVERED", "2024-01-04"),   # DUPLICATE
        (5, 104, 450.00, "SHIPPED", "2024-01-05"),
        (6, 105, 175.25, "PENDING", "2024-01-06"),
        # Row 7 missing
        (8, 107, 85.50,  "SHIPPED", "2024-01-08"),
        (9, 108, 220.00, "PENDING", "2024-01-09"),
        (10, 109, 310.00, "DELIVERED", "2024-01-10"),
        (11, 110, 500.00, "SHIPPED", "2024-01-11"),    # EXTRA row
    ])
    conn.commit()
    conn.close()

    return src_path, tgt_path


def test_data_diff(src_path, tgt_path):
    """Test DB↔DB data comparison."""
    print("\n" + "=" * 70)
    print("TEST 1: DATA DIFF (DB↔DB)")
    print("=" * 70)

    src_config = ConnectionConfig(platform="sqlite", database=src_path)
    tgt_config = ConnectionConfig(platform="sqlite", database=tgt_path)

    src_conn = get_connector("sqlite", src_config)
    tgt_conn = get_connector("sqlite", tgt_config)
    src_conn.connect()
    tgt_conn.connect()

    check = get_check("data")
    config = CheckConfig(
        check_type="data",
        source_table="orders",
        target_table="orders",
        join_keys=["ORDER_ID"],
        ignore_columns=[],
        where="",
        chunk_size=10000,
        extra={},
    )

    result = check.run(src_conn, tgt_conn, config)

    print(f"\nStatus: {result.status}")
    print(f"Message: {result.message}")
    print(f"Metrics:")
    for k, v in (result.metrics or {}).items():
        print(f"  {k}: {v}")
    if result.details is not None and not (hasattr(result.details, 'empty') and result.details.empty):
        print(f"Details (first 5):")
        if hasattr(result.details, 'head'):
            print(result.details.head())
        else:
            for d in result.details[:5]:
                print(f"  {d}")

    src_conn.close()
    tgt_conn.close()
    return result


def test_duplicates(tgt_path):
    """Test duplicate detection on target (which has a duplicate row)."""
    print("\n" + "=" * 70)
    print("TEST 2: DUPLICATE CHECK")
    print("=" * 70)

    src_config = ConnectionConfig(platform="sqlite", database=tgt_path)
    tgt_config = ConnectionConfig(platform="sqlite", database=tgt_path)

    src_conn = get_connector("sqlite", src_config)
    tgt_conn = get_connector("sqlite", tgt_config)
    src_conn.connect()
    tgt_conn.connect()

    check = get_check("duplicate")
    config = CheckConfig(
        check_type="duplicate",
        source_table="orders",
        target_table="orders",
        join_keys=["ORDER_ID"],
        ignore_columns=[],
        where="",
        chunk_size=10000,
        extra={},
    )

    result = check.run(src_conn, tgt_conn, config)

    print(f"\nStatus: {result.status}")
    print(f"Message: {result.message}")
    print(f"Metrics:")
    for k, v in (result.metrics or {}).items():
        print(f"  {k}: {v}")

    src_conn.close()
    tgt_conn.close()
    return result


def test_aggregation(src_path, tgt_path):
    """Test aggregation check (SUM/AVG/MIN/MAX)."""
    print("\n" + "=" * 70)
    print("TEST 3: AGGREGATION CHECK")
    print("=" * 70)

    src_config = ConnectionConfig(platform="sqlite", database=src_path)
    tgt_config = ConnectionConfig(platform="sqlite", database=tgt_path)

    src_conn = get_connector("sqlite", src_config)
    tgt_conn = get_connector("sqlite", tgt_config)
    src_conn.connect()
    tgt_conn.connect()

    check = get_check("aggregate")
    config = CheckConfig(
        check_type="aggregate",
        source_table="orders",
        target_table="orders",
        join_keys=["ORDER_ID"],
        ignore_columns=[],
        where="",
        chunk_size=10000,
        extra={"columns": ["AMOUNT"]},
    )

    result = check.run(src_conn, tgt_conn, config)

    print(f"\nStatus: {result.status}")
    print(f"Message: {result.message}")
    print(f"Metrics:")
    for k, v in (result.metrics or {}).items():
        print(f"  {k}: {v}")

    src_conn.close()
    tgt_conn.close()
    return result


if __name__ == "__main__":
    src_path, tgt_path = create_test_dbs()
    print(f"Source DB: {src_path}")
    print(f"Target DB: {tgt_path}")

    r1 = test_data_diff(src_path, tgt_path)
    r2 = test_duplicates(tgt_path)
    r3 = test_aggregation(src_path, tgt_path)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Data Diff:    {r1.status} (expect FAIL — differences exist)")
    print(f"  Duplicates:   {r2.status} (expect FAIL — ORDER_ID=4 duplicated)")
    print(f"  Aggregation:  {r3.status} (expect FAIL — SUMs differ)")
    print()

    # Cleanup
    os.unlink(src_path)
    os.unlink(tgt_path)
