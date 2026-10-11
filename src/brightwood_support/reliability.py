"""Reliability helpers: retries, timeouts, fallbacks and fault injection.

A real agent calls models and customer systems that fail, hang, or return junk.
These helpers make each failure handled and testable, and FaultInjector lets a
test or an eval cause those failures on purpose.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeout
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class CallTimeout(Exception):
    """The call did not finish within the allowed time."""


class AllAttemptsFailed(Exception):
    """Every attempt or fallback failed. `errors` holds each failure in order."""

    def __init__(self, errors: list[BaseException]) -> None:
        super().__init__(f"all {len(errors)} attempts failed; last: {errors[-1]!r}")
        self.errors = errors


def retry(
    fn: Callable[[], T],
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call fn, retrying on the given errors with exponential backoff.

    The delay doubles each time (0.5s, 1s, 2s, ...) up to max_delay. Errors not
    listed in retry_on (for example a bad request) are raised at once.
    """
    errors: list[BaseException] = []
    for attempt in range(attempts):
        try:
            return fn()
        except retry_on as error:
            errors.append(error)
            if attempt < attempts - 1:
                sleep(min(max_delay, base_delay * (2**attempt)))
    raise AllAttemptsFailed(errors)


def call_with_timeout(fn: Callable[[], T], seconds: float) -> T:
    """Return fn() or raise CallTimeout.

    Limit: Python cannot kill a running thread, so a timed-out call keeps running
    in the background until it ends. The caller moves on; it does not wait.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=seconds)
    except _FutureTimeout:
        raise CallTimeout(f"no result after {seconds}s") from None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def with_fallback(*fns: Callable[[], T]) -> tuple[T, int]:
    """Try each function in order. Return (result, index of the one that worked).

    The index lets the caller log which fallback served the request.
    """
    errors: list[BaseException] = []
    for index, fn in enumerate(fns):
        try:
            return fn(), index
        except Exception as error:  # noqa: BLE001 - any failure moves to the next option
            errors.append(error)
    raise AllAttemptsFailed(errors)


class FaultInjector:
    """Wrap a function so it fails on purpose, to test the handling around it.

    fail_times: fail this many calls, then behave normally.
    always:     fail every call.
    delay:      sleep this many seconds before each call (to trigger timeouts).
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        fail_times: int = 0,
        always: bool = False,
        error: BaseException | None = None,
        delay: float = 0.0,
    ) -> None:
        self.fn = fn
        self.fail_times = fail_times
        self.always = always
        self.error = error or RuntimeError("injected failure")
        self.delay = delay
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.always or self.calls <= self.fail_times:
            raise self.error
        return self.fn(*args, **kwargs)
