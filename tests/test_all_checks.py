"""Comprehensive DB↔DB test for ALL check types.

Tests every check type registered in the engine against SQLite databases
with known differences. Verifies:
- row_count: mismatch detection, tolerance, percentage
- metadata: column type/order differences
- null_check: NULL and empty string detection
- duplicate: duplicate groups and count comparison
- data: full column-level diff with keyed drill-down
- aggregate: SUM/AVG/MIN/MAX mismatch detection

Run: cd /Users/amannem/Downloads && python3 -m etl_validator.tests.test_all_checks
"""
import sys
import os
import sqlite3
import tempfile
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etl_validator.connectors.base import ConnectionConfig
from etl_validator.connectors.registry import get_connector
from etl_validator.checks.registry import get_check
from etl_validator.checks.base import CheckConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"

results = []


def report(test_name, check_result, expected_status, notes=""):
    """Record and print test result."""
    actual = str(check_result.status).split(".")[-1] if check_result else "ERROR"
    expected_str = expected_status.upper()
    ok = actual.upper() == expected_str
    symbol = PASS if ok else FAIL
    results.append((test_name, ok, actual, expected_str))
    print(f"  {symbol} {test_name}: got={actual}, expected={expected_str}")
    if notes:
        print(f"       {notes}")
    if not ok and check_result:
        print(f"       Message: {check_result.message}")
    return ok


def create_databases():
    """Create source and target SQLite DBs with controlled differences."""
    src_path = os.path.join(tempfile.gettempdir(), "etl_thorough_src.db")
    tgt_path = os.path.join(tempfile.gettempdir(), "etl_thorough_tgt.db")

    # ═══════════════════════════════════════════════════════════════════
    # SOURCE DATABASE
    # ═══════════════════════════════════════════════════════════════════
    conn = sqlite3.connect(src_path)

    # Table: orders (main comparison table)
    conn.execute("DROP TABLE IF EXISTS orders")
    conn.execute("""
        CREATE TABLE orders (
            ORDER_ID INTEGER PRIMARY KEY,
            CUSTOMER_ID INTEGER NOT NULL,
            AMOUNT REAL NOT NULL,
            DISCOUNT REAL,
            STATUS TEXT NOT NULL,
            REGION TEXT,
            ORDER_DATE TEXT NOT NULL
        )
    """)
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", [
        (1,  100, 250.00, 10.0,  "SHIPPED",   "EAST",  "2024-01-01"),
        (2,  101, 150.50, None,  "PENDING",   "WEST",  "2024-01-02"),
        (3,  102, 320.75, 15.0,  "SHIPPED",   "EAST",  "2024-01-03"),
        (4,  103, 99.99,  5.0,   "DELIVERED", "NORTH", "2024-01-04"),
        (5,  104, 450.00, 20.0,  "SHIPPED",   "SOUTH", "2024-01-05"),
        (6,  105, 175.25, None,  "PENDING",   "EAST",  "2024-01-06"),
        (7,  106, 600.00, 30.0,  "DELIVERED", "WEST",  "2024-01-07"),
        (8,  107, 85.50,  None,  "SHIPPED",   None,    "2024-01-08"),
        (9,  108, 220.00, 12.0,  "PENDING",   "NORTH", "2024-01-09"),
        (10, 109, 310.00, 25.0,  "DELIVERED", "SOUTH", "2024-01-10"),
    ])

    # Table: identical_table (for pass-case testing)
    conn.execute("DROP TABLE IF EXISTS identical_table")
    conn.execute("CREATE TABLE identical_table (ID INTEGER, NAME TEXT, VALUE REAL)")
    conn.executemany("INSERT INTO identical_table VALUES (?, ?, ?)", [
        (1, "Alice", 100.0),
        (2, "Bob", 200.0),
        (3, "Charlie", 300.0),
    ])

    # Table: schema_test (for metadata check)
    conn.execute("DROP TABLE IF EXISTS schema_test")
    conn.execute("""
        CREATE TABLE schema_test (
            ID INTEGER,
            NAME TEXT,
            AMOUNT REAL,
            CREATED_DATE TEXT
        )
    """)

    conn.commit()
    conn.close()

    # ═══════════════════════════════════════════════════════════════════
    # TARGET DATABASE
    # ═══════════════════════════════════════════════════════════════════
    conn = sqlite3.connect(tgt_path)

    # Table: orders — differences from source:
    # - Row 3: AMOUNT 320.75→321.00, STATUS SHIPPED→DELIVERED
    # - Row 7: MISSING (deleted)
    # - Row 11: EXTRA (inserted)
    # - Row 4: DUPLICATED (same values twice)
    # - Row 8: REGION NULL→'EAST' (null changed to value)
    # - Row 2: DISCOUNT NULL→0.0 (null changed to zero)
    conn.execute("DROP TABLE IF EXISTS orders")
    conn.execute("""
        CREATE TABLE orders (
            ORDER_ID INTEGER,
            CUSTOMER_ID INTEGER NOT NULL,
            AMOUNT REAL NOT NULL,
            DISCOUNT REAL,
            STATUS TEXT NOT NULL,
            REGION TEXT,
            ORDER_DATE TEXT NOT NULL
        )
    """)
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", [
        (1,  100, 250.00, 10.0,  "SHIPPED",   "EAST",  "2024-01-01"),
        (2,  101, 150.50, 0.0,   "PENDING",   "WEST",  "2024-01-02"),   # DISCOUNT: NULL→0.0
        (3,  102, 321.00, 15.0,  "DELIVERED", "EAST",  "2024-01-03"),   # AMOUNT+STATUS changed
        (4,  103, 99.99,  5.0,   "DELIVERED", "NORTH", "2024-01-04"),
        (4,  103, 99.99,  5.0,   "DELIVERED", "NORTH", "2024-01-04"),   # DUPLICATE
        (5,  104, 450.00, 20.0,  "SHIPPED",   "SOUTH", "2024-01-05"),
        (6,  105, 175.25, None,  "PENDING",   "EAST",  "2024-01-06"),
        # Row 7 MISSING
        (8,  107, 85.50,  None,  "SHIPPED",   "EAST",  "2024-01-08"),   # REGION: NULL→'EAST'
        (9,  108, 220.00, 12.0,  "PENDING",   "NORTH", "2024-01-09"),
        (10, 109, 310.00, 25.0,  "DELIVERED", "SOUTH", "2024-01-10"),
        (11, 110, 500.00, 10.0,  "SHIPPED",   "WEST",  "2024-01-11"),   # EXTRA row
    ])

    # Table: identical_table (exactly same data)
    conn.execute("DROP TABLE IF EXISTS identical_table")
    conn.execute("CREATE TABLE identical_table (ID INTEGER, NAME TEXT, VALUE REAL)")
    conn.executemany("INSERT INTO identical_table VALUES (?, ?, ?)", [
        (1, "Alice", 100.0),
        (2, "Bob", 200.0),
        (3, "Charlie", 300.0),
    ])

    # Table: schema_test — different schema (extra column, type change)
    conn.execute("DROP TABLE IF EXISTS schema_test")
    conn.execute("""
        CREATE TABLE schema_test (
            ID INTEGER,
            NAME TEXT,
            AMOUNT TEXT,
            CREATED_DATE TEXT,
            EXTRA_COL TEXT
        )
    """)

    conn.commit()
    conn.close()

    return src_path, tgt_path


def get_conns(src_path, tgt_path):
    src_cfg = ConnectionConfig(platform="sqlite", database=src_path)
    tgt_cfg = ConnectionConfig(platform="sqlite", database=tgt_path)
    src = get_connector("sqlite", src_cfg)
    tgt = get_connector("sqlite", tgt_cfg)
    src.connect()
    tgt.connect()
    return src, tgt


# ══════════════════════════════════════════════════════════════════════════════
# TEST SUITE
# ══════════════════════════════════════════════════════════════════════════════

def test_row_count(src, tgt):
    print("\n┌─────────────────────────────────────────────────────────────────┐")
    print("│  CHECK: ROW COUNT                                               │")
    print("└─────────────────────────────────────────────────────────────────┘")

    check = get_check("row_count")

    # Test 1: Mismatch (10 src vs 11 tgt)
    cfg = CheckConfig(check_type="row_count", source_table="orders", target_table="orders")
    r = check.run(src, tgt, cfg)
    report("Row count mismatch (10 vs 11)", r, "FAIL",
           f"src={r.metrics['src_row_count']}, tgt={r.metrics['tgt_row_count']}, diff={r.metrics['row_count_diff']}")

    # Test 2: Exact match
    cfg = CheckConfig(check_type="row_count", source_table="identical_table", target_table="identical_table")
    r = check.run(src, tgt, cfg)
    report("Row count exact match (3 vs 3)", r, "PASS")

    # Test 3: With tolerance (1 row tolerance should make 10 vs 11 pass)
    cfg = CheckConfig(check_type="row_count", source_table="orders", target_table="orders", tolerance=1)
    r = check.run(src, tgt, cfg)
    report("Row count within tolerance=1", r, "PASS")

    # Test 4: With WHERE filter
    cfg = CheckConfig(check_type="row_count", source_table="orders", target_table="orders",
                      where="STATUS = 'PENDING'")
    r = check.run(src, tgt, cfg)
    report(f"Row count with WHERE filter (PENDING)", r, "PASS",
           f"src={r.metrics['src_row_count']}, tgt={r.metrics['tgt_row_count']}")


def test_metadata(src, tgt):
    print("\n┌─────────────────────────────────────────────────────────────────┐")
    print("│  CHECK: METADATA (SCHEMA)                                       │")
    print("└─────────────────────────────────────────────────────────────────┘")

    check = get_check("metadata")

    # Test 1: Identical schema
    cfg = CheckConfig(check_type="metadata", source_table="identical_table", target_table="identical_table")
    r = check.run(src, tgt, cfg)
    report("Schema exact match", r, "PASS")

    # Test 2: Different schema (extra column + type change)
    cfg = CheckConfig(check_type="metadata", source_table="schema_test", target_table="schema_test",
                      ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Schema mismatch (extra col + type diff)", r, "FAIL",
           f"Message: {r.message}")


def test_null_check(src, tgt):
    print("\n┌─────────────────────────────────────────────────────────────────┐")
    print("│  CHECK: NULL / EMPTY                                            │")
    print("└─────────────────────────────────────────────────────────────────┘")

    check = get_check("null_check")

    # Test 1: Full table null comparison (DISCOUNT has NULLs, REGION has NULLs)
    cfg = CheckConfig(check_type="null_check", source_table="orders", target_table="orders",
                      ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Null check (DISCOUNT/REGION have null diffs)", r, "FAIL",
           f"Metrics: {r.metrics.get('mismatched_columns', 'N/A')}")

    # Test 2: Identical table (no nulls differ)
    cfg = CheckConfig(check_type="null_check", source_table="identical_table", target_table="identical_table",
                      ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Null check on identical data", r, "PASS")

    # Test 3: Specific columns only
    cfg = CheckConfig(check_type="null_check", source_table="orders", target_table="orders",
                      columns=["STATUS", "ORDER_DATE"], ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Null check on non-null columns (STATUS, ORDER_DATE)", r, "PASS")


def test_duplicate(src, tgt):
    print("\n┌─────────────────────────────────────────────────────────────────┐")
    print("│  CHECK: DUPLICATE                                               │")
    print("└─────────────────────────────────────────────────────────────────┘")

    check = get_check("duplicate")

    # Test 1: Check ORDER_ID duplicates (src has none, tgt has ORDER_ID=4 twice)
    cfg = CheckConfig(check_type="duplicate", source_table="orders", target_table="orders",
                      columns=["ORDER_ID"], ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Duplicate check ORDER_ID (src=0 dupes, tgt=1 dupe group)", r, "FAIL",
           f"src_groups={r.metrics.get('src_duplicate_groups')}, tgt_groups={r.metrics.get('tgt_duplicate_groups')}")

    # Test 2: Identical table (no dupes)
    cfg = CheckConfig(check_type="duplicate", source_table="identical_table", target_table="identical_table",
                      columns=["ID"], ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Duplicate check on unique data", r, "PASS")

    # Test 3: Check composite key duplicates (ORDER_ID + CUSTOMER_ID)
    cfg = CheckConfig(check_type="duplicate", source_table="orders", target_table="orders",
                      columns=["ORDER_ID", "CUSTOMER_ID"], ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Duplicate check composite key (ORDER_ID+CUSTOMER_ID)", r, "FAIL",
           f"tgt_duplicate_rows={r.metrics.get('tgt_duplicate_rows')}")


def test_data_diff(src, tgt):
    print("\n┌─────────────────────────────────────────────────────────────────┐")
    print("│  CHECK: DATA COMPARISON (FULL DIFF)                             │")
    print("└─────────────────────────────────────────────────────────────────┘")

    check = get_check("data")

    # Test 1: Full diff with join key
    cfg = CheckConfig(check_type="data", source_table="orders", target_table="orders",
                      join_keys=["ORDER_ID"], ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Data diff with JOIN key (ORDER_ID)", r, "FAIL",
           f"match={r.metrics.get('match_pct')}%, mismatch_cols={r.metrics.get('mismatch_columns')}, "
           f"strategy={r.metrics.get('strategy')}")

    # Verify specific metrics
    m = r.metrics
    assert m["src_row_count"] == 10, f"Expected src=10, got {m['src_row_count']}"
    assert m["tgt_row_count"] == 11, f"Expected tgt=11, got {m['tgt_row_count']}"
    print(f"       ✓ Row counts correct: src=10, tgt=11")
    assert m["rows_only_in_source"] > 0, "Expected rows only in source (row 7)"
    print(f"       ✓ rows_only_in_source={m['rows_only_in_source']} (row 7 missing from target)")
    assert m["rows_only_in_target"] > 0, "Expected rows only in target (row 11)"
    print(f"       ✓ rows_only_in_target={m['rows_only_in_target']} (row 11 extra in target)")

    # Test 2: Identical data (should PASS)
    cfg = CheckConfig(check_type="data", source_table="identical_table", target_table="identical_table",
                      join_keys=["ID"], ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Data diff on identical tables", r, "PASS",
           f"match={r.metrics.get('match_pct')}%, strategy={r.metrics.get('strategy')}")

    # Test 3: Without join keys (auto-detect or positional)
    cfg = CheckConfig(check_type="data", source_table="orders", target_table="orders",
                      join_keys=[], ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Data diff without explicit join key", r, "FAIL",
           f"match={r.metrics.get('match_pct')}%, keys={r.metrics.get('join_keys_used')}")

    # Test 4: With ignore_columns (ignore the changed columns → should reduce diffs)
    cfg = CheckConfig(check_type="data", source_table="orders", target_table="orders",
                      join_keys=["ORDER_ID"], ignore_columns=["AMOUNT", "STATUS", "DISCOUNT", "REGION"])
    r = check.run(src, tgt, cfg)
    report("Data diff ignoring changed columns", r, "FAIL",
           f"match={r.metrics.get('match_pct')}% (still fails due to row count diff)")

    # Test 5: With WHERE filter (only SHIPPED — row 7 is SHIPPED in src but missing in tgt)
    cfg = CheckConfig(check_type="data", source_table="orders", target_table="orders",
                      join_keys=["ORDER_ID"], ignore_columns=[],
                      where="STATUS = 'DELIVERED'")
    r = check.run(src, tgt, cfg)
    report("Data diff with WHERE='DELIVERED'", r, "FAIL",
           f"src={r.metrics.get('src_row_count')}, tgt={r.metrics.get('tgt_row_count')}")

    # Test 6: Pyramid disabled (skip fingerprint, go straight to full)
    cfg = CheckConfig(check_type="data", source_table="orders", target_table="orders",
                      join_keys=["ORDER_ID"], ignore_columns=[],
                      extra={"pyramid": False})
    r = check.run(src, tgt, cfg)
    report("Data diff with pyramid=False", r, "FAIL",
           f"strategy={r.metrics.get('strategy')} (should skip fingerprint)")


def test_aggregate(src, tgt):
    print("\n┌─────────────────────────────────────────────────────────────────┐")
    print("│  CHECK: AGGREGATE (SUM/AVG/MIN/MAX)                             │")
    print("└─────────────────────────────────────────────────────────────────┘")

    check = get_check("aggregate")

    # Test 1: Auto-detect numeric columns
    cfg = CheckConfig(check_type="aggregate", source_table="orders", target_table="orders",
                      join_keys=[], ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Aggregate auto-detect (all numeric cols)", r, "FAIL",
           f"measures={r.metrics.get('measure_columns')}, id_cols={r.metrics.get('id_columns')}")

    # Test 2: Specific column (AMOUNT)
    cfg = CheckConfig(check_type="aggregate", source_table="orders", target_table="orders",
                      columns=["AMOUNT"], join_keys=[], ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Aggregate on AMOUNT only", r, "FAIL",
           f"Message: {r.message}")

    # Test 3: Identical table aggregates (should pass)
    cfg = CheckConfig(check_type="aggregate", source_table="identical_table", target_table="identical_table",
                      columns=["VALUE"], join_keys=[], ignore_columns=[])
    r = check.run(src, tgt, cfg)
    report("Aggregate on identical data (VALUE)", r, "PASS")

    # Test 4: With tolerance
    cfg = CheckConfig(check_type="aggregate", source_table="orders", target_table="orders",
                      columns=["AMOUNT"], join_keys=[], ignore_columns=[],
                      extra={"tolerance": 1000.0})  # Large tolerance
    r = check.run(src, tgt, cfg)
    report("Aggregate with large tolerance", r, "PASS",
           f"tolerance=1000.0 should cover AMOUNT diffs")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    src_path, tgt_path = create_databases()
    print(f"Source: {src_path}")
    print(f"Target: {tgt_path}")

    src, tgt = get_conns(src_path, tgt_path)

    try:
        test_row_count(src, tgt)
        test_metadata(src, tgt)
        test_null_check(src, tgt)
        test_duplicate(src, tgt)
        test_data_diff(src, tgt)
        test_aggregate(src, tgt)
    finally:
        src.close()
        tgt.close()
        os.unlink(src_path)
        os.unlink(tgt_path)

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "═" * 70)
    print("  COMPREHENSIVE TEST SUMMARY")
    print("═" * 70)
    passed = sum(1 for _, ok, _, _ in results if ok)
    failed = sum(1 for _, ok, _, _ in results if not ok)
    for name, ok, actual, expected in results:
        symbol = "✅" if ok else "❌"
        print(f"  {symbol} {name}")
    print(f"\n  Total: {passed}/{len(results)} passed, {failed} failed")
    if failed:
        print(f"\n  FAILED TESTS:")
        for name, ok, actual, expected in results:
            if not ok:
                print(f"    ❌ {name}: got {actual}, expected {expected}")
        sys.exit(1)
    else:
        print(f"\n  🎉 ALL TESTS PASSED")
