import asyncio
import time
import logging

logger = logging.getLogger("dhan-redis-hub.governor")

class RateGovernor:
    """
    Async Rate Governor for Dhan API endpoints.
    Enforces a strict global 1.0s minimum time interval across ALL requests to Dhan API
    as well as endpoint-specific minimum intervals across all workers/pollers.
    Handles automatic backoff on 429 errors.
    """
    def __init__(self):
        self._last_call_times: dict[str, float] = {}
        self._global_last_call_time: float = 0.0
        self._lock = asyncio.Lock()

    async def wait_for_slot(self, endpoint_category: str = "global", min_interval_secs: float = 1.25):
        """
        Blocks until the minimum interval has elapsed both globally (1.25s) and for `endpoint_category`.
        """
        async with self._lock:
            now = time.monotonic()
            
            global_elapsed = now - self._global_last_call_time
            cat_last_time = self._last_call_times.get(endpoint_category, 0.0)
            cat_elapsed = now - cat_last_time
            
            required_wait = max(
                1.25 - global_elapsed,
                min_interval_secs - cat_elapsed,
                0.0
            )
            
            if required_wait > 0:
                logger.debug(f"RateGovernor: Throttling {endpoint_category} for {required_wait:.3f}s")
                await asyncio.sleep(required_wait)
            
            call_time = time.monotonic()
            self._global_last_call_time = call_time
            self._last_call_times[endpoint_category] = call_time

    async def handle_429_backoff(self, retry_count: int = 1, base_backoff_secs: float = 2.0):
        """
        Exponential backoff helper when a 429 is encountered.
        """
        backoff = base_backoff_secs * (2 ** (retry_count - 1))
        logger.warning(f"RateGovernor: Received 429 Rate Limit from Dhan API. Backing off for {backoff:.2f}s...")
        try:
            from alerts import dispatch_error_alert
            # Project defaults to the request context that triggered the call, so
            # a 429 caused by one project is not attributed to the hub itself.
            dispatch_error_alert(
                f"Dhan API HTTP 429 Rate Limit hit. Backing off for {backoff:.2f}s",
                component="Rate Governor",
            )
        except Exception:
            pass
        await asyncio.sleep(backoff)

rate_governor = RateGovernor()
