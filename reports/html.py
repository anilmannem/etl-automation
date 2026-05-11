"""Standalone HTML report generation (like Great Expectations Data Docs)."""

from __future__ import annotations

import html
import logging
from pathlib import Path

from ..checks.base import Status
from ..engine.executor import SuiteResult

logger = logging.getLogger(__name__)

_STATUS_COLORS = {
    "Pass": "#28a745",
    "Fail": "#dc3545",
    "Warning": "#ffc107",
    "Error": "#6c757d",
    "Not Applicable": "#17a2b8",
}


def write_html_report(suite_result: SuiteResult, output_path: str | Path) -> Path:
    """Generate a self-contained HTML report."""
    output_path = Path(output_path)

    rows_html = ""
    for r in suite_result.results:
        color = _STATUS_COLORS.get(str(r.status), "#333")
        metrics_str = ", ".join(f"{k}={v}" for k, v in r.metrics.items())
        rows_html += f"""
        <tr>
            <td>{html.escape(r.check_type)}</td>
            <td style="color: white; background-color: {color}; font-weight: bold; text-align: center;">
                {html.escape(str(r.status))}
            </td>
            <td>{html.escape(r.message)}</td>
            <td style="font-size: 0.85em; color: #555;">{html.escape(metrics_str)}</td>
        </tr>"""

    # Detail sections
    details_html = ""
    for i, r in enumerate(suite_result.results, 1):
        if r.details is not None and len(r.details) > 0:
            total_rows = len(r.details)
            display_limit = 200
            truncated = total_rows > display_limit
            truncation_note = (
                f'<p style="color: #6c757d; font-style: italic;">'
                f'Showing {display_limit} of {total_rows:,} mismatch rows. '
                f'See Excel report for full details.</p>'
                if truncated else ""
            )
            details_html += f"""
            <h3>Detail: {html.escape(r.check_type)} ({total_rows:,} rows)</h3>
            {truncation_note}
            <div style="overflow-x: auto; max-height: 400px; overflow-y: auto;">
                {r.details.head(display_limit).to_html(index=False, classes="detail-table")}
            </div>"""

    summary = suite_result.summary_dict()
    overall_color = _STATUS_COLORS.get(summary["status"], "#333")

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>ETL Validation Report — {html.escape(suite_result.suite_name)}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               margin: 2em; background: #f8f9fa; }}
        h1 {{ color: #212529; }}
        .badge {{ display: inline-block; padding: 0.3em 0.8em; border-radius: 4px;
                  color: white; font-weight: bold; font-size: 1.1em; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(4, 1fr);
                        gap: 1em; margin: 1.5em 0; }}
        .summary-card {{ background: white; border-radius: 8px; padding: 1.2em;
                        box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }}
        .summary-card .num {{ font-size: 2em; font-weight: bold; }}
        .summary-card .label {{ color: #6c757d; font-size: 0.9em; }}
        table {{ border-collapse: collapse; width: 100%; background: white;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 8px;
                overflow: hidden; }}
        th {{ background: #343a40; color: white; padding: 0.75em 1em; text-align: left; }}
        td {{ padding: 0.6em 1em; border-bottom: 1px solid #dee2e6; }}
        tr:hover {{ background: #f1f3f5; }}
        .detail-table {{ font-size: 0.85em; }}
        .detail-table th {{ background: #6c757d; }}
    </style>
</head>
<body>
    <h1>ETL Validation Report</h1>
    <p>
        <strong>Suite:</strong> {html.escape(suite_result.suite_name)} &nbsp;
        <strong>Run:</strong> {html.escape(suite_result.run_id)} &nbsp;
        <span class="badge" style="background-color: {overall_color};">{html.escape(summary['status'])}</span>
    </p>

    <div class="summary-grid">
        <div class="summary-card">
            <div class="num">{summary['total']}</div>
            <div class="label">Total Checks</div>
        </div>
        <div class="summary-card">
            <div class="num" style="color: #28a745;">{summary['passed']}</div>
            <div class="label">Passed</div>
        </div>
        <div class="summary-card">
            <div class="num" style="color: #dc3545;">{summary['failed']}</div>
            <div class="label">Failed</div>
        </div>
        <div class="summary-card">
            <div class="num">{summary['duration_s']}s</div>
            <div class="label">Duration</div>
        </div>
    </div>

    <h2>Check Results</h2>
    <table>
        <thead>
            <tr><th>Check Type</th><th>Status</th><th>Message</th><th>Metrics</th></tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>

    {details_html}

    <p style="color: #adb5bd; margin-top: 3em; font-size: 0.8em;">
        Generated by ETL Validator v1.0
    </p>
</body>
</html>"""

    output_path.write_text(page_html, encoding="utf-8")
    logger.info("HTML report written: %s", output_path)
    return output_path
