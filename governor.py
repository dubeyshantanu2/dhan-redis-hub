import asyncio
import time
import logging

logger = logging.getLogger("dhan-redis-hub.governor")

class RateGovernor:
    """
    Async Rate Governor for Dhan API endpoints.
    Enforces minimum time intervals per endpoint type across all workers/pollers.
    Handles automatic backoff on 429 errors.
    """
    def __init__(self):
        self._last_call_times: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait_for_slot(self, endpoint_category: str, min_interval_secs: float):
        """
        Blocks until the minimum interval for `endpoint_category` has elapsed since the last call.
        """
        async with self._lock:
            now = time.monotonic()
            last_time = self._last_call_times.get(endpoint_category, 0.0)
            elapsed = now - last_time
            
            if elapsed < min_interval_secs:
                wait_time = min_interval_secs - elapsed
                logger.debug(f"RateGovernor: Throttling {endpoint_category} for {wait_time:.3f}s")
                await asyncio.sleep(wait_time)
            
            self._last_call_times[endpoint_category] = time.monotonic()

    async def handle_429_backoff(self, retry_count: int = 1, base_backoff_secs: float = 2.0):
        """
        Exponential backoff helper when a 429 is encountered.
        """
        backoff = base_backoff_secs * (2 ** (retry_count - 1))
        logger.warning(f"RateGovernor: Received 429 Rate Limit from Dhan API. Backing off for {backoff:.2f}s...")
        await asyncio.sleep(backoff)

rate_governor = RateGovernor()
