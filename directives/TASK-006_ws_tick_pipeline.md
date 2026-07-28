# TASK-006 Repair WebSocket Tick Pipeline
**Date:** 2026-07-28
**Status:** complete
**Assigned to:** Code Generator Agent → Debug ✅ CLEAN → QA ✅ PASS

## Goal
`dhan:ticks:<security_id>` carries live ticks — including 5-level depth and cumulative volume for the NIFTY futures leg — so that client projects consume real-time market data from Redis Pub/Sub instead of opening their own direct connections to `api.dhan.co`.

## Background
Audit `docs/AUDIT_2026-07-28_AEOLUS_READINESS.md` (2026-07-28, live market hours) found that `ws_feed.py` never publishes a single tick. Three independent defects, each alone sufficient:

1. **Never subscribes.** `ws_feed.py:46` connects then drops straight into `ws.recv()`. Dhan v2 requires the client to *send* a subscribe request after connecting. `self._subscribed_instruments` (`ws_feed.py:20`) is assigned once and never referenced again.
2. **Cannot parse packets.** Dhan v2 market data is binary. `ws_feed.py:67-69` reduces non-text frames to `{"raw": message.hex()}`, then `ws_feed.py:71-74` asks that dict for `security_id`/`LTP` — keys that cannot exist. The condition is permanently `False`, making the Redis write (`:77`) and `publish` (`:81`) unreachable.
3. **LTP-only shape.** Even if 1 and 2 were fixed, `_handle_ws_message` extracts nothing but LTP — no depth, no volume, no `total_buy/sell_quantity`.

**Consequence:** every project's `client.subscribe_ticks()` blocks forever. AEOLUS opened its own direct Dhan WebSocket (`feed_ws.py`) as the only way to get depth/volume — violating the hub's founding constraint that only `dhan-redis-hub` talks to `api.dhan.co`.

## Acceptance Criteria
- `ws_feed.py` sends a valid v2 subscription for a configured instrument universe after connecting.
- Binary market-data packets are parsed into dicts (not hex strings).
- Published payload for the futures leg includes `LTP`, `volume`, `total_buy_quantity`, `total_sell_quantity`, `high`, `low`, and 5-level `depth`.
- Ticks are published to `dhan:ticks:<security_id>`, consumable by the existing `client.subscribe_ticks()` without changes to `client.py`.
- The NIFTY current-month futures contract is resolved automatically — no monthly manual edit.
- `/quote` REST responses keep their existing Dhan-REST field shape (no schema drift for current consumers).
- Reconnect uses exponential backoff and survives token expiry.
- Test suite passes with no regression.

## Inputs Required
- `ws_feed.py`, `config.py`, `app.py`, `client.py`, `poller.py`, `requirements.txt`
- `dhanhq` SDK `MarketFeed` (v2 binary protocol, already proven against this API in AEOLUS `feed_ws.py`)
- Dhan scrip master CSV (already downloaded by `poller.fetch_and_cache_scrip_master()`)

## Expected Output
- Rewritten `ws_feed.py`; additive changes to `config.py`, `poller.py`, `requirements.txt`
- Tests in `tests/test_ws_feed.py`
- Debug report `reports/debug/TASK-006_debug-report.md`, QA report `reports/qa/TASK-006_qa-report.md`
- `CHANGELOG.md` + `docs/ARCHITECTURE.md` updated, Obsidian session log synced

## Edge Cases / Constraints
- **Key collision:** `ws_feed.py:77` currently writes to `dhan:quote:{id}` — the same key `poller.fetch_and_cache_quote()` owns, but with WebSocket field names instead of REST ones. Harmless today only because the line is unreachable. Fixing the parser without addressing this would make `/quote` return two schemas at random.
- Futures contract rolls monthly; resolution must be automatic.
- Dhan access token expires daily — reconnect must re-read credentials from Redis, not cache them.
- Single Fly machine (`min_machines_running = 1`), so exactly one WS connection — no cross-instance fan-out needed.
- Market hours only: outside 09:15–15:30 IST the feed is legitimately silent. Silence is not an error.

## Questions for Architect
1. Raw `websockets` with hand-rolled `struct` parsing, or the `dhanhq` SDK's `MarketFeed`?
2. How is the current-month futures security ID resolved without manual monthly edits?
3. Where does the WS snapshot write go, given the `dhan:quote:` collision?
