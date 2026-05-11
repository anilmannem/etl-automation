"""Suite executor — runs checks sequentially or in parallel.

Supports:
- Sequential execution (default, safe for shared connections)
- Parallel execution via concurrent.futures (each check gets its own connections)
- Per-check timing and progress callbacks
- Fail-fast mode: stop on first failure
- Check dependency ordering via ``depends_on``
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

from ..checks.base import CheckConfig, CheckResult, Status
from ..checks.registry import get_check
from ..connectors.base import BaseConnector
from ..connectors.registry import get_connector
from .resilience import CircuitBreaker, CircuitBreakerConfig, retry, RetryConfig
from .suite_loader import TestSuite

logger = logging.getLogger(__name__)

# ── Default resilience configs ────────────────────────────────────────────────
_RETRY = RetryConfig(max_retries=2, base_delay_s=2.0, jitter=True)
_CB_CONFIG = CircuitBreakerConfig(failure_threshold=5, timeout_s=30.0)


# ── Suite Result ──────────────────────────────────────────────────────────────

@dataclass
class CheckTiming:
    """Per-check timing information."""
    check_type: str
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def duration_s(self) -> float:
        return round(self.end_time - self.start_time, 3)


@dataclass
class SuiteResult:
    """Aggregated results for a full test suite run."""
    run_id: str
    suite_name: str
    results: list[CheckResult] = field(default_factory=list)
    timings: list[CheckTiming] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == Status.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == Status.FAIL)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.status == Status.ERROR)

    @property
    def overall_status(self) -> Status:
        if any(r.status == Status.ERROR for r in self.results):
            return Status.ERROR
        if any(r.status == Status.FAIL for r in self.results):
            return Status.FAIL
        return Status.PASS

    @property
    def quality_score(self) -> float:
        """Weighted quality score 0–100. Industry standard: weight by check severity."""
        if not self.results:
            return 100.0
        weights = {
            "row_count": 3.0,
            "metadata": 2.0,
            "null_check": 2.0,
            "duplicate": 2.5,
            "data": 5.0,
            "aggregate": 3.0,
        }
        total_weight = 0.0
        weighted_pass = 0.0
        for r in self.results:
            w = weights.get(r.check_type, 1.0)
            total_weight += w
            if r.status == Status.PASS:
                weighted_pass += w
            elif r.status == Status.WARNING:
                weighted_pass += w * 0.5  # partial credit
        return round((weighted_pass / total_weight) * 100, 1) if total_weight else 100.0

    def summary_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "suite": self.suite_name,
            "status": str(self.overall_status),
            "quality_score": self.quality_score,
            "total": len(self.results),
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "duration_s": round(self.duration_seconds, 2),
        }

    def slowest_checks(self, n: int = 5) -> list[dict]:
        """Return the N slowest checks for performance insight."""
        sorted_t = sorted(self.timings, key=lambda t: t.duration_s, reverse=True)
        return [{"check": t.check_type, "duration_s": t.duration_s} for t in sorted_t[:n]]


# ── Single check runner (with retry + circuit breaker) ────────────────────────

def _run_single_check(
    check_config: CheckConfig,
    src_conn: BaseConnector,
    tgt_conn: BaseConnector,
    circuit_breaker: CircuitBreaker | None = None,
) -> tuple[CheckResult, CheckTiming]:
    """Run one check with resilience wrappers."""
    timing = CheckTiming(check_type=check_config.check_type)
    timing.start_time = time.time()

    try:
        check = get_check(check_config.check_type)

        @retry(_RETRY)
        def _execute():
            if circuit_breaker:
                with circuit_breaker:
                    return check.run(src_conn, tgt_conn, check_config)
            else:
                return check.run(src_conn, tgt_conn, check_config)

        result = _execute()

    except Exception as e:
        logger.error("Check %s → ERROR: %s", check_config.check_type, e)
        result = CheckResult(
            check_type=check_config.check_type,
            status=Status.ERROR,
            message=str(e),
        )

    timing.end_time = time.time()
    return result, timing


# ── Parallel check runner (each check gets its own connections) ───────────────

def _run_check_with_own_connections(
    check_config: CheckConfig,
    suite: TestSuite,
) -> tuple[CheckResult, CheckTiming]:
    """Spawn fresh connections for a single check (safe for thread pools)."""
    src = get_connector(suite.source_platform, suite.source)
    tgt = get_connector(suite.target_platform, suite.target)
    try:
        src.connect()
        tgt.connect()
        return _run_single_check(check_config, src, tgt)
    finally:
        src.close()
        tgt.close()


# ── Dependency resolver ──────────────────────────────────────────────────────

def _resolve_execution_order(checks: list[CheckConfig]) -> list[list[CheckConfig]]:
    """Group checks into execution waves respecting ``depends_on``.

    Checks without dependencies go in wave 0 and can run in parallel.
    Checks depending on wave-0 checks go in wave 1, etc.
    """
    name_to_check = {}
    for c in checks:
        name_to_check[c.check_type] = c

    # Build adjacency
    deps = {}
    for c in checks:
        dep_list = c.extra.get("depends_on", [])
        if isinstance(dep_list, str):
            dep_list = [dep_list]
        deps[c.check_type] = set(dep_list)

    waves: list[list[CheckConfig]] = []
    placed = set()

    while len(placed) < len(checks):
        wave = []
        for c in checks:
            if c.check_type in placed:
                continue
            if deps[c.check_type].issubset(placed):
                wave.append(c)
        if not wave:
            # Circular dependency — just dump remaining
            wave = [c for c in checks if c.check_type not in placed]
            logger.warning("Circular dependency detected, forcing execution: %s",
                           [c.check_type for c in wave])
        for c in wave:
            placed.add(c.check_type)
        waves.append(wave)

    return waves


# ── Main executor ─────────────────────────────────────────────────────────────

def execute_suite(
    suite: TestSuite,
    run_id: str | None = None,
    parallel: bool = False,
    max_workers: int = 4,
    fail_fast: bool = False,
    progress_callback: Callable[[int, int, CheckResult], None] | None = None,
) -> SuiteResult:
    """Execute every check in a TestSuite.

    Parameters
    ----------
    suite : the loaded test suite
    run_id : optional run identifier
    parallel : if True, run independent checks concurrently
    max_workers : thread-pool size for parallel mode
    fail_fast : stop on first failure
    progress_callback : called after each check with (current, total, result)
    """
    run_id = run_id or uuid.uuid4().hex[:12]
    logger.info("Starting suite '%s' (run=%s, parallel=%s) with %d check(s)",
                suite.name, run_id, parallel, len(suite.checks))

    start = time.time()
    results: list[CheckResult] = []
    timings: list[CheckTiming] = []
    cb = CircuitBreaker(_CB_CONFIG)

    waves = _resolve_execution_order(suite.checks)

    if parallel:
        # ── Parallel: each wave runs concurrently, waves run sequentially ──
        for wave_idx, wave in enumerate(waves):
            logger.info("Wave %d: %d check(s) in parallel", wave_idx + 1, len(wave))
            with ThreadPoolExecutor(max_workers=min(max_workers, len(wave))) as pool:
                futures = {
                    pool.submit(_run_check_with_own_connections, cc, suite): cc
                    for cc in wave
                }
                for future in as_completed(futures):
                    cc = futures[future]
                    result, timing = future.result()
                    results.append(result)
                    timings.append(timing)
                    logger.info("%s → %s (%.2fs): %s",
                                cc.check_type, result.status,
                                timing.duration_s, result.message)
                    if progress_callback:
                        progress_callback(len(results), len(suite.checks), result)
                    if fail_fast and result.status in (Status.FAIL, Status.ERROR):
                        logger.warning("Fail-fast: stopping after %s", cc.check_type)
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
            if fail_fast and any(r.status in (Status.FAIL, Status.ERROR) for r in results):
                break
    else:
        # ── Sequential: shared connections, retry + circuit breaker ──
        src_conn = get_connector(suite.source_platform, suite.source)
        tgt_conn = get_connector(suite.target_platform, suite.target)
        try:
            src_conn.connect()
            tgt_conn.connect()

            flat_checks = [c for wave in waves for c in wave]
            for i, check_config in enumerate(flat_checks, 1):
                logger.info("[%d/%d] Running: %s", i, len(flat_checks), check_config.check_type)

                result, timing = _run_single_check(check_config, src_conn, tgt_conn, cb)
                results.append(result)
                timings.append(timing)

                logger.info("[%d/%d] %s → %s (%.2fs): %s",
                            i, len(flat_checks), check_config.check_type,
                            result.status, timing.duration_s, result.message)

                if progress_callback:
                    progress_callback(i, len(flat_checks), result)

                if fail_fast and result.status in (Status.FAIL, Status.ERROR):
                    logger.warning("Fail-fast: stopping after %s", check_config.check_type)
                    break
        finally:
            src_conn.close()
            tgt_conn.close()

    duration = time.time() - start
    suite_result = SuiteResult(
        run_id=run_id,
        suite_name=suite.name,
        results=results,
        timings=timings,
        duration_seconds=duration,
    )
    logger.info(
        "Suite '%s' completed in %.1fs — score=%.1f%% — %s",
        suite.name, duration, suite_result.quality_score,
        suite_result.summary_dict(),
    )
    return suite_result
