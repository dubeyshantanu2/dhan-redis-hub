# Architecture Decision Record — TASK-429
**Date:** 2026-07-27
**Decision Status:** APPROVED

## Problem Statement
`background_universe_poller()` in `app.py` causes HTTP 429 rate limit errors by executing 8 requests every 2 seconds across NIFTY, BANKNIFTY, FINNIFTY, and SENSEX.

## Decision Made
1. Add `await asyncio.sleep(1.0)` between index loops in `background_universe_poller()`.
2. Increase post-pass cycle sleep to 5.0s.
3. Ensure `fetch_and_cache_expiry_list()` caches expiries under `dhan:expirylist:<SYMBOL>` for 12 hours (`ex=43200`).
4. Include `SENSEX` in `settings.default_indices`.

## Component Boundaries
- `app.py`: Update `background_universe_poller()` sleep intervals.
- `config.py`: Add `SENSEX` to `default_indices`.
- `poller.py`: Hardened caching logic for `fetch_and_cache_expiry_list()`.
- `tests/test_redis_hub.py`: Test coverage.
