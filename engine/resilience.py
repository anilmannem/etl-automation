"""Retry logic with exponential backoff and circuit breaker pattern.

Industry reference: Netflix Hystrix, Polly (.NET), resilience4j (Java).
"""

from __future__ import annotations

import logging
import random
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)


# ── Retry with Exponential Backoff ────────────────────────────────────────────

@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple = (Exception,)


def retry(config: RetryConfig | None = None):
    """Decorator: retry a function with exponential backoff + jitter.

    Example:
        @retry(RetryConfig(max_retries=3))
        def query_teradata():
            ...
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exc = e
                    if attempt == config.max_retries:
                        logger.error(
                            "All %d retries exhausted for %s: %s",
                            config.max_retries, func.__name__, e,
                        )
                        raise
                    delay = min(
                        config.base_delay_s * (config.exponential_base ** attempt),
                        config.max_delay_s,
                    )
                    if config.jitter:
                        delay *= 0.5 + random.random()
                    logger.warning(
                        "Retry %d/%d for %s after %.1fs: %s",
                        attempt + 1, config.max_retries,
                        func.__name__, delay, e,
                    )
                    time.sleep(delay)
            raise last_exc  # unreachable, but satisfies type checkers
        return wrapper
    return decorator


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED = "closed"        # normal operation
    OPEN = "open"            # failing, reject fast
    HALF_OPEN = "half_open"  # testing if recovered


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open."""


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5        # failures before opening
    success_threshold: int = 2        # successes in half-open to close
    timeout_s: float = 30.0           # how long to stay open before half-open
    window_s: float = 60.0            # rolling window for failure counting


class CircuitBreaker:
    """Circuit breaker for database connections.

    Prevents thundering-herd retries when a database is down.

    Usage:
        cb = CircuitBreaker()
        with cb:
            result = conn.execute_query(sql)
    """

    def __init__(self, config: CircuitBreakerConfig | None = None):
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failures: deque[float] = deque()
        self._successes_in_half_open = 0
        self._last_failure_time = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            # Check if timeout has elapsed → move to half-open
            if time.time() - self._last_failure_time >= self.config.timeout_s:
                logger.info("Circuit breaker → HALF_OPEN")
                self._state = CircuitState.HALF_OPEN
                self._successes_in_half_open = 0
        return self._state

    def __enter__(self):
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerOpen(
                f"Circuit breaker is OPEN. Will retry after "
                f"{self.config.timeout_s - (time.time() - self._last_failure_time):.0f}s"
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._on_success()
        else:
            self._on_failure()
        return False  # don't suppress the exception

    def _on_success(self):
        if self._state == CircuitState.HALF_OPEN:
            self._successes_in_half_open += 1
            if self._successes_in_half_open >= self.config.success_threshold:
                logger.info("Circuit breaker → CLOSED (recovered)")
                self._state = CircuitState.CLOSED
                self._failures.clear()
        # In CLOSED state, just continue

    def _on_failure(self):
        now = time.time()
        self._failures.append(now)
        self._last_failure_time = now

        # Expire old failures outside the window
        cutoff = now - self.config.window_s
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()

        if self._state == CircuitState.HALF_OPEN:
            logger.warning("Circuit breaker → OPEN (failed during half-open)")
            self._state = CircuitState.OPEN
            self._successes_in_half_open = 0
        elif len(self._failures) >= self.config.failure_threshold:
            logger.warning(
                "Circuit breaker → OPEN (%d failures in %.0fs window)",
                len(self._failures), self.config.window_s,
            )
            self._state = CircuitState.OPEN
