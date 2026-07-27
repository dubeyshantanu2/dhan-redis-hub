# TASK-429 Rate Limit Optimization
**Date:** 2026-07-27
**Status:** in-progress
**Assigned to:** Code Generator Agent

## Goal
Eliminate HTTP 429 rate limit errors in `background_universe_poller()` by spacing Dhan API index requests by 1.0s, increasing the cycle sleep to 5.0s, and caching expiry lists in Redis for 12 hours (`ex=43200`).

## Acceptance Criteria
- Spacing of 1.0s between index iterations in `background_universe_poller()`.
- Sleep interval of 5.0s at the end of each poller pass.
- `dhan:expirylist:<SYMBOL>` cached with 12-hour TTL (`ex=43200`).
- SENSEX included in default indices.
- All test suites pass without regression.

## Inputs Required
- `app.py`
- `poller.py`
- `config.py`

## Expected Output
- Code changes in `app.py`, `poller.py`, `config.py`, and `tests/test_redis_hub.py`.
- Debug & QA reports.
