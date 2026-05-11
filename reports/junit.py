"""JUnit XML report — for CI/CD pipeline integration (Jenkins, GitLab, GitHub Actions)."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from ..checks.base import Status
from ..engine.executor import SuiteResult

logger = logging.getLogger(__name__)


def write_junit_xml(suite_result: SuiteResult, output_path: str | Path) -> Path:
    """Write JUnit-compatible XML report.

    Most CI systems (Jenkins, GitLab CI, GitHub Actions) can parse this
    format to display test results natively.
    """
    output_path = Path(output_path)

    testsuite = ET.Element("testsuite", {
        "name": suite_result.suite_name,
        "tests": str(len(suite_result.results)),
        "failures": str(suite_result.failed),
        "errors": str(suite_result.errors),
        "time": str(round(suite_result.duration_seconds, 2)),
    })

    for r in suite_result.results:
        testcase = ET.SubElement(testsuite, "testcase", {
            "classname": suite_result.suite_name,
            "name": r.check_type,
        })

        if r.status == Status.FAIL:
            failure = ET.SubElement(testcase, "failure", {
                "type": "AssertionError",
                "message": r.message,
            })
            # Add metrics as text content
            metrics_text = "\n".join(f"{k}: {v}" for k, v in r.metrics.items())
            failure.text = metrics_text

        elif r.status == Status.ERROR:
            error = ET.SubElement(testcase, "error", {
                "type": "RuntimeError",
                "message": r.message,
            })

        # Add stdout with the message
        stdout = ET.SubElement(testcase, "system-out")
        stdout.text = r.message

    tree = ET.ElementTree(testsuite)
    ET.indent(tree, space="  ")
    tree.write(str(output_path), encoding="unicode", xml_declaration=True)
    logger.info("JUnit XML report written: %s", output_path)
    return output_path
