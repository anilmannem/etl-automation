"""Excel report writer — generates styled XLSX output."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..checks.base import CheckResult, Status
from ..engine.executor import SuiteResult

logger = logging.getLogger(__name__)


def _status_fill(workbook, status_str: str):
    """Return an xlsxwriter format for a status value."""
    if status_str == "Pass":
        return workbook.add_format({"bg_color": "#90EE90"})  # lightgreen
    elif status_str == "Fail":
        return workbook.add_format({"bg_color": "#F08080"})  # lightcoral
    elif status_str == "Warning":
        return workbook.add_format({"bg_color": "#FFD700"})  # gold
    return workbook.add_format({})


def write_excel_report(suite_result: SuiteResult, output_path: str | Path) -> Path:
    """Write a comprehensive Excel report for a suite run.

    Creates:
    - 'Summary' sheet with all check results and pass/fail colouring
    - One detail sheet per failed check (if the check produced details)
    """
    output_path = Path(output_path)
    logger.info("Writing Excel report to %s", output_path)

    # Build summary DataFrame
    rows = []
    for r in suite_result.results:
        row = {"Check Type": r.check_type, "Status": str(r.status), "Message": r.message}
        row.update(r.metrics)
        rows.append(row)
    summary_df = pd.DataFrame(rows)

    with pd.ExcelWriter(str(output_path), engine="xlsxwriter") as writer:
        # Summary sheet
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        workbook = writer.book
        worksheet = writer.sheets["Summary"]

        # Apply status colouring
        status_col_idx = summary_df.columns.get_loc("Status")
        for row_idx, status_val in enumerate(summary_df["Status"], start=1):
            fmt = _status_fill(workbook, status_val)
            worksheet.write(row_idx, status_col_idx, status_val, fmt)

        # Auto-fit column widths
        for col_idx, col_name in enumerate(summary_df.columns):
            col_max = summary_df[col_name].astype(str).str.len().max()
            col_max = col_max if pd.notna(col_max) else 0
            max_len = max(int(col_max), len(col_name)) + 2
            worksheet.set_column(col_idx, col_idx, min(max_len, 60))

        # Detail sheets for failed checks
        sheet_num = 1
        for r in suite_result.results:
            if r.details is not None and len(r.details) > 0:
                sheet_name = f"Detail_{sheet_num}_{r.check_type}"[:31]
                r.details.to_excel(writer, sheet_name=sheet_name, index=False)
                sheet_num += 1

    logger.info("Excel report written: %s", output_path)
    return output_path


def write_multi_suite_report(suite_results: list[SuiteResult], output_path: str | Path) -> Path:
    """Write results from multiple suites into a single Excel workbook."""
    output_path = Path(output_path)

    with pd.ExcelWriter(str(output_path), engine="xlsxwriter") as writer:
        all_rows = []
        for sr in suite_results:
            for r in sr.results:
                row = {
                    "Suite": sr.suite_name,
                    "Run ID": sr.run_id,
                    "Check Type": r.check_type,
                    "Status": str(r.status),
                    "Message": r.message,
                }
                row.update(r.metrics)
                all_rows.append(row)

        summary_df = pd.DataFrame(all_rows)
        summary_df.to_excel(writer, sheet_name="All Results", index=False)

        workbook = writer.book
        worksheet = writer.sheets["All Results"]
        status_col_idx = summary_df.columns.get_loc("Status")
        for row_idx, status_val in enumerate(summary_df["Status"], start=1):
            fmt = _status_fill(workbook, status_val)
            worksheet.write(row_idx, status_col_idx, status_val, fmt)

    return output_path
