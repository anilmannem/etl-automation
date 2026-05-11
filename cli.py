"""CLI entry point — run ETL validation suites from the command line.

Usage examples:
    # Run a single test suite
    etl-validate run tests/order_migration.yaml

    # Run with parallel execution
    etl-validate run tests/suite.yaml --parallel --workers 8

    # Run all suites in a directory
    etl-validate run-dir tests/

    # Run with JUnit output (for CI/CD)
    etl-validate run tests/suite.yaml --output junit --output-path results.xml

    # Profile a table and auto-generate a test suite
    etl-validate profile --table DB.SCHEMA.TABLE --dsn "$SNC_DSN" --output suite.yaml

    # Show historical results and trends
    etl-validate history --suite order_migration --days 7

    # Quick hash-based data comparison
    etl-validate compare --src DB.SRC.TABLE --tgt DB.TGT.TABLE --keys ORDER_ID --strategy hash
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click

from .engine.suite_loader import load_suite, load_suites_from_dir
from .engine.executor import execute_suite
from .engine.result_store import ResultStore
from .reports.excel import write_excel_report, write_multi_suite_report
from .reports.junit import write_junit_xml
from .reports.html import write_html_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@click.group()
def cli():
    """ETL Validator — Industry-grade ETL testing automation."""


@cli.command()
@click.argument("suite_path", type=click.Path(exists=True))
@click.option("--connections", "-c", type=click.Path(exists=True), default=None,
              help="Path to connections YAML file")
@click.option("--output", "-o", type=click.Choice(["json", "junit", "html", "excel", "all"]),
              default="all", help="Output format")
@click.option("--output-path", "-p", type=click.Path(), default=None,
              help="Output file path (auto-generated if omitted)")
@click.option("--fail-on", type=click.Choice(["fail", "error", "none"]),
              default="fail", help="Exit with code 1 on this status")
@click.option("--store/--no-store", default=True,
              help="Save results to the result store")
@click.option("--parallel", is_flag=True, default=False,
              help="Run independent checks in parallel")
@click.option("--workers", "-w", default=4, help="Thread pool size for parallel mode")
@click.option("--fail-fast", is_flag=True, default=False,
              help="Stop on first failure")
def run(suite_path, connections, output, output_path, fail_on, store, parallel, workers, fail_fast):
    """Run a single test suite."""
    suite = load_suite(suite_path, connections)
    result = execute_suite(suite, parallel=parallel, max_workers=workers, fail_fast=fail_fast)

    # Store results
    if store:
        rs = ResultStore()
        rs.record_suite(result)
        rs.close()

    # Generate reports
    base_name = Path(suite_path).stem
    if output in ("excel", "all"):
        path = output_path or f"{base_name}_report.xlsx"
        write_excel_report(result, path)
        click.echo(f"Excel report: {path}")

    if output in ("junit", "all"):
        path = output_path or f"{base_name}_report.xml"
        write_junit_xml(result, path)
        click.echo(f"JUnit XML: {path}")

    if output in ("html", "all"):
        path = output_path or f"{base_name}_report.html"
        write_html_report(result, path)
        click.echo(f"HTML report: {path}")

    if output == "json":
        import json
        data = result.summary_dict()
        data["checks"] = [r.to_dict() for r in result.results]
        click.echo(json.dumps(data, indent=2, default=str))

    # Print summary
    summary = result.summary_dict()
    click.echo(f"\n{'='*50}")
    click.echo(f"Suite:    {summary['suite']}")
    click.echo(f"Status:   {summary['status']}")
    click.echo(f"Score:    {summary.get('quality_score', 'N/A')}%")
    click.echo(f"Passed:   {summary['passed']}/{summary['total']}")
    click.echo(f"Failed:   {summary['failed']}")
    click.echo(f"Duration: {summary['duration_s']}s")
    if result.timings:
        click.echo(f"Slowest:  {result.slowest_checks(3)}")
    click.echo(f"{'='*50}")

    # Exit code
    if fail_on == "fail" and result.failed > 0:
        sys.exit(1)
    elif fail_on == "error" and result.errors > 0:
        sys.exit(1)


@cli.command("run-dir")
@click.argument("directory", type=click.Path(exists=True))
@click.option("--connections", "-c", type=click.Path(exists=True), default=None)
@click.option("--output-path", "-p", type=click.Path(), default="all_suites_report.xlsx")
@click.option("--fail-on", type=click.Choice(["fail", "error", "none"]),
              default="fail")
@click.option("--store/--no-store", default=True)
def run_dir(directory, connections, output_path, fail_on, store):
    """Run all test suites in a directory."""
    suites = load_suites_from_dir(directory, connections)
    if not suites:
        click.echo("No test suites found.")
        return

    results = []
    rs = ResultStore() if store else None

    for suite in suites:
        click.echo(f"\nRunning suite: {suite.name}")
        result = execute_suite(suite)
        results.append(result)
        if rs:
            rs.record_suite(result)

    if rs:
        rs.close()

    # Consolidated report
    write_multi_suite_report(results, output_path)
    click.echo(f"\nConsolidated report: {output_path}")

    # Summary
    total_passed = sum(r.passed for r in results)
    total_failed = sum(r.failed for r in results)
    total_checks = sum(len(r.results) for r in results)
    click.echo(f"\n{'='*50}")
    click.echo(f"Suites:   {len(results)}")
    click.echo(f"Checks:   {total_checks}")
    click.echo(f"Passed:   {total_passed}")
    click.echo(f"Failed:   {total_failed}")
    click.echo(f"{'='*50}")

    if fail_on == "fail" and total_failed > 0:
        sys.exit(1)


@cli.command()
@click.option("--suite", "-s", default=None, help="Filter by suite name")
@click.option("--days", "-d", default=30, help="Number of days to look back")
def history(suite, days):
    """Show historical test results."""
    rs = ResultStore()
    df = rs.get_history(suite, days)
    rs.close()

    if df.empty:
        click.echo("No results found.")
        return

    click.echo(df.to_string(index=False))


@cli.command()
@click.option("--table", "-t", required=True, help="Fully-qualified table name to profile")
@click.option("--dsn", required=True, help="DSN for the connection")
@click.option("--user", "-u", default="", help="Database user")
@click.option("--password", "-P", default="", help="Database password")
@click.option("--platform", default="teradata", help="Database platform (teradata or csv)")
@click.option("--target-table", default=None, help="Target table (defaults to same as source)")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output YAML file path")
@click.option("--sample-pct", default=100.0, help="Sampling percentage for profiling")
def profile(table, dsn, user, password, platform, target_table, output, sample_pct):
    """Profile a table and auto-generate a YAML test suite."""
    from .connectors.base import ConnectionConfig
    from .connectors.registry import get_connector
    from .engine.profiler import profile_table, generate_suite_yaml

    config = ConnectionConfig(
        platform=platform, dsn=dsn, user=user, password=password,
    )
    conn = get_connector(platform, config)
    conn.connect()

    try:
        tp = profile_table(conn, table, sample_pct=sample_pct)
    finally:
        conn.close()

    click.echo(f"\nTable: {tp.table}")
    click.echo(f"Rows:  {tp.row_count:,}")
    click.echo(f"Cols:  {tp.column_count}")
    if tp.duplicate_key_candidates:
        click.echo(f"Key candidates: {', '.join(tp.duplicate_key_candidates)}")

    click.echo("\nColumn Profiles:")
    for cp in tp.columns:
        line = f"  {cp.name:<30} {cp.data_type:<25} null={cp.null_pct:.1f}%"
        if cp.min_val is not None:
            line += f"  range=[{cp.min_val}, {cp.max_val}]"
        if cp.distinct_count >= 0:
            line += f"  distinct={cp.distinct_count}"
        click.echo(line)

    tgt = target_table or table
    yaml_str = generate_suite_yaml(table, tgt, tp, output_path=output)

    if not output:
        click.echo(f"\n{'='*50}")
        click.echo("Generated Test Suite (YAML):")
        click.echo(f"{'='*50}")
        click.echo(yaml_str)
    else:
        click.echo(f"\nSuite written to: {output}")


@cli.command()
@click.option("--src", required=True, help="Source table (fully-qualified)")
@click.option("--tgt", required=True, help="Target table (fully-qualified)")
@click.option("--dsn", required=True, help="DSN for connections")
@click.option("--user", "-u", default="", help="Database user")
@click.option("--password", "-P", default="", help="Database password")
@click.option("--keys", "-k", required=True, help="Comma-separated join key columns")
@click.option("--strategy", type=click.Choice(["hash", "full", "sample"]),
              default="hash", help="Comparison strategy")
@click.option("--sample-pct", default=10.0, help="Sample percentage (for strategy=sample)")
@click.option("--platform", default="teradata", help="Database platform (teradata or csv)")
@click.option("--where", "-w", default="", help="WHERE filter clause")
def compare(src, tgt, dsn, user, password, keys, strategy, sample_pct, platform, where):
    """Quick ad-hoc data comparison between two tables."""
    import tempfile
    import yaml

    key_list = [k.strip() for k in keys.split(",")]

    suite_data = {
        "test_suite": "adhoc_compare",
        "source": {"platform": platform, "table": src, "dsn": dsn, "user": user, "password": password},
        "target": {"platform": platform, "table": tgt, "dsn": dsn, "user": user, "password": password},
        "checks": [
            {"type": "row_count"},
            {
                "type": "data",
                "join_keys": key_list,
                "strategy": strategy,
                "sample_pct": sample_pct,
                "column_drill_down": True,
            },
        ],
    }
    if where:
        suite_data["filters"] = {"where": where}

    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        yaml.dump(suite_data, f)
        temp_path = f.name

    suite = load_suite(temp_path)
    result = execute_suite(suite)

    summary = result.summary_dict()
    click.echo(f"\n{'='*50}")
    click.echo(f"Compare: {src} vs {tgt}")
    click.echo(f"Strategy: {strategy}")
    click.echo(f"Status: {summary['status']} (score={summary.get('quality_score', 'N/A')}%)")
    for r in result.results:
        click.echo(f"  {r.check_type}: {r.status} — {r.message}")
    click.echo(f"{'='*50}")

    if result.failed > 0:
        sys.exit(1)


def main():
    cli()


if __name__ == "__main__":
    main()
