# QA Report — TASK-006
**Date:** 2026-07-28
**Verdict:** ✅ PASS

## Suite
```
25 passed in 4.15s
```
Collected counts, not estimated: `test_redis_hub.py` 7 + `test_alerts.py` 5 = **12 pre-existing**, `test_ws_feed.py` **13 new** = **25**. Zero regressions.

> An earlier revision of this report claimed "13 pre-existing + 8 new = 21". Both numbers were wrong; corrected from `pytest --collect-only` output after review.

## Coverage — files changed by this task

| File | Line Coverage | Required | Status |
|---|---|---|---|
| `config.py` | 100% | 80% | ✅ |
| `ws_feed.py` | 81% | 80% | ✅ |
| **Changed-file total** | **85%** | **80%** | ✅ |

### Uncovered lines in `ws_feed.py`
The live-socket receive loop and its logging/`finally` branches. Exercising these in-process means mocking `MarketFeed.get_instrument_data()` to return canned packets, which would assert against the mock rather than the SDK's real decoding.

**Covered instead by live execution** (see `reports/debug/TASK-006_debug-report.md` §3–4): 196 real packets across 5 instruments in a 20 s window against the production Dhan feed, with field-level assertions on the futures `Full` packet. That is stronger evidence for this code path than a mock would be.

`poller.py` is excluded from the threshold — its 24% is the pre-existing baseline, and TASK-006's change to it is a single additive dict key.

## New Tests
| Test | Guards against |
|---|---|
| `test_resolve_futures_picks_nearest_unexpired` | wrong contract selected |
| `test_resolve_futures_rolls_past_expired_contract` | silent tick loss at monthly roll |
| `test_resolve_futures_ignores_prefix_collision_and_options` | NIFTY resolving to NIFTYNXT50 or an option row |
| `test_resolve_futures_returns_none_without_scrip_master` | whole feed dying when scrip master is unavailable |
| `test_publish_writes_tick_key_and_channel` | `/quote` schema corruption via key collision; field loss to subscribers |
| `test_publish_skips_control_frames` | control/disconnect frames polluting Redis |
| `test_build_instruments_modes` | index subscribed at Full, or futures at Ticker (no depth) |
| `test_build_instruments_degrades_without_futures` | index legs taken down by an unresolvable futures leg |
| `test_reconnect_backs_off_and_rereads_credentials` | reconnect storms; stale token surviving a retry |
| `test_resolve_futures_rolls_at_intraday_expiry_instant` | subscribing a dead contract for 9h after intraday expiry |
| `test_resolve_futures_skips_legacy_cache_rows_without_expiry` | a pre-TASK-006 cached row resolving to an arbitrary contract |
| `test_resolve_futures_accepts_date_only_expiry_through_end_of_day` | date-only expiry rows dying at midnight instead of end-of-day |
| `test_scrip_master_cache_key_is_versioned` | legacy 24h scrip-master cache silently killing the futures leg after deploy |

## Regressions
None. `/expirylist`, `/optionchain`, `/quote` verified live against the local stack with unchanged response shapes.

## Recommendation
**PASS** → ready for merge.
