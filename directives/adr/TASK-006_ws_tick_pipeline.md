# Architecture Decision Record — TASK-006
**Date:** 2026-07-28
**Decision Status:** APPROVED

## Problem Statement
`ws_feed.py` hand-rolls a Dhan v2 WebSocket client on raw `websockets` and gets three things wrong: it never sends a subscribe frame, it cannot decode the binary market-data protocol, and it only ever looked for LTP. Net effect: `dhan:ticks:<security_id>` is permanently empty, `client.subscribe_ticks()` blocks forever in every consuming project, and AEOLUS bypasses the hub with its own direct Dhan connection to get depth and volume.

## Decision Made
**Delete the hand-rolled WebSocket client and drive `dhanhq.MarketFeed` instead.**

The binary wire protocol (`struct`-level packet unpacking for Ticker / Quote / Full / Depth frames, subscribe-frame construction, disconnect codes) already exists, tested and vendor-maintained, in the `dhanhq` SDK. AEOLUS's `feed_ws.py` has been running that exact SDK against this exact API in production. Reimplementing ~200 lines of `struct.unpack` against an undocumented binary format is the single highest-risk thing this repo could do, and it is optional.

`DhanWebSocketHub` keeps its public shape (`__init__(redis_client)`, `async start()`, `stop()`) so `app.py` needs no change. Internally it becomes a supervisor loop around `MarketFeed.connect()` / `get_instrument_data()` / `disconnect()`, publishing each parsed packet to `dhan:ticks:<security_id>`.

The current-month futures contract is resolved at connect time from the scrip master the hub **already downloads and caches**, so the monthly roll needs no human intervention.

## Rationale
- Vendor SDK owns the wire format; when Dhan changes packet layout, an SDK bump fixes it rather than a debugging session against hex dumps.
- `MarketFeed` emits exactly the field names TASK-006 requires (`LTP`, `volume`, `total_buy_quantity`, `total_sell_quantity`, `high`, `low`, `depth[]` with `bid_price`/`bid_quantity`/`ask_price`/`ask_quantity`) — verified by reading the SDK source at `dhanhq/marketfeed.py:470-489`.
- Publishing the SDK dict verbatim means `client.subscribe_ticks()` needs no change, and downstream consumers get the same field names AEOLUS's `feed_ws.py` already parses — so AEOLUS's migration is a transport swap, not a re-model.
- Reusing `fetch_and_cache_scrip_master()` for futures resolution costs one additional CSV column and no new network call.

## Alternatives Considered & Rejected
1. **Fix the hand-rolled client in place** — rejected. Requires implementing Dhan's binary protocol from scratch: subscribe-frame packing, per-response-code unpacking, market-depth packet walking. High defect risk, permanent maintenance burden, and duplicates code already installed.
2. **Hardcode the futures security ID in `config.py` / an env var** — rejected. Breaks silently every month at contract roll, and the failure mode is "ticks quietly stop for the most important instrument", which is exactly the class of bug this task exists to remove.
3. **Publish to `dhan:quote:<id>` (preserving the original line)** — rejected. `poller.fetch_and_cache_quote()` owns that key with Dhan **REST** field names (`last_price`, `buy_quantity`, `ohlc.high`, `depth.buy`). WS packets use different names (`LTP`, `total_buy_quantity`, `high`, `depth[].bid_price`). Sharing the key makes `/quote` return two schemas at random. WS snapshots go to `dhan:tick:<id>` instead.
4. **Subscribe every instrument in the scrip master** — rejected as YAGNI. Start with the four indices plus the NIFTY futures leg; the universe is config-driven, so adding an instrument is a one-line edit.

## Component Boundaries
| File Path | Responsibility | Dependencies |
|---|---|---|
| `ws_feed.py` | **Rewrite.** Supervisor loop around `MarketFeed`; publish to Pub/Sub; snapshot to `dhan:tick:<id>` | `dhanhq`, `redis`, `config`, `auth_sync`, `poller` |
| `config.py` | **Additive.** WS instrument universe + backoff/TTL settings | — |
| `poller.py` | **Additive.** Carry `expiry` through `fetch_and_cache_scrip_master()`'s parsed map | — |
| `requirements.txt` | **Additive.** `dhanhq>=2.0.0` | — |
| `tests/test_ws_feed.py` | **New.** Futures resolution + packet publishing | `ws_feed`, `unittest.mock` |
| `app.py` | **Unchanged.** `ws_hub.start()` / `.stop()` contract preserved | — |
| `client.py` | **Unchanged.** `subscribe_ticks()` already reads `dhan:ticks:<id>` | — |

## API Contracts

```python
# ws_feed.py — public surface unchanged, so app.py needs no edit
class DhanWebSocketHub:
    def __init__(self, redis_client: Redis) -> None: ...
    async def start(self) -> None:
        """Supervisor loop. Re-reads credentials from Redis on every reconnect
        (tokens expire daily). Exponential backoff 1s → 60s, reset after a
        sustained connection. Returns only when stop() is called."""
    def stop(self) -> None: ...

    def _build_instruments(self) -> list[tuple[int, str, int]]:
        """(exchange_segment, security_id, request_code) tuples for MarketFeed.
        Indices at Ticker; each configured futures leg at Full."""

    def _publish(self, packet: dict) -> None:
        """Publish packet verbatim to 'dhan:ticks:<security_id>' and snapshot
        to 'dhan:tick:<security_id>' with ttl_tick_snapshot. No-op when the
        packet carries no security_id (control/disconnect frames)."""


# ws_feed.py — module-level, testable without a live socket
async def resolve_futures_security_id(redis_client: Redis, symbol: str) -> str | None:
    """Nearest non-expired futures contract for `symbol` from the cached scrip
    master. Matches SEM_CUSTOM_SYMBOL '<SYMBOL> <MON> FUT' exactly, so NIFTY
    does not match NIFTYNXT50. Returns None if unresolvable — caller subscribes
    the index legs anyway rather than failing the whole feed."""


# poller.py — additive only; existing keys keep their meaning
scrip_map[symbol] = {
    "security_id": str, "exchange": str, "segment": str,
    "lot_size": str, "expiry": str,   # <-- new: SEM_EXPIRY_DATE, '' when absent
}
```

## Data Flow

```
Dhan v2 WSS ──binary──► dhanhq.MarketFeed (SDK unpacks struct)
                              │  parsed dict
                              ▼
                    DhanWebSocketHub._publish()
                              │
             ┌────────────────┴────────────────┐
             ▼                                 ▼
   PUBLISH dhan:ticks:<id>            SET dhan:tick:<id> (60s)
             │                        (cold-start snapshot)
             ▼
   client.subscribe_ticks(id) ──► AEOLUS / ARES / Kronos …
                                  (no direct api.dhan.co connection)

Contract roll: fetch_and_cache_scrip_master() ──► resolve_futures_security_id()
```

## Performance & Security
- One WSS connection per Fly machine; `min_machines_running = 1` guarantees exactly one. No cross-instance fan-out required.
- Publish path is O(1) per packet, no Redis round-trip on the read side for subscribers.
- Credentials are read from `dhan:auth` on every reconnect and never cached in an instance attribute — a daily token rotation heals on the next reconnect.
- No credentials in logs. `security_id` and packet type only.
- Outside 09:15–15:30 IST the feed is legitimately silent; silence must not trigger reconnect storms or error alerts.

## Definition of Done
**Status: IMPLEMENTED 2026-07-28.** All items verified — see `reports/debug/TASK-006_debug-report.md` and `reports/qa/TASK-006_qa-report.md`.

- [x] `ws_feed.py` rewritten on `MarketFeed`; no `struct` or raw `websockets` use remains
- [x] Futures leg auto-resolves; no hardcoded contract ID — resolved `61093` live
- [x] Published futures packet carries LTP, volume, total_buy/sell_quantity, high, low, 5-level depth
- [x] `dhan:quote:<id>` untouched by the WS path; `/quote` schema unchanged — `--scan 'dhan:quote:*'` returned 0
- [x] `app.py` and `client.py` unmodified
- [x] Tests pass, no regression in `tests/test_redis_hub.py` / `tests/test_alerts.py` — 25/25
- [x] Live verification during market hours: 196 ticks in 20s across 5 instruments

### Added during review (2026-07-28)
- [x] Scrip-master cache key versioned to `dhan:scrip_master:v2` — a legacy payload without `expiry` would otherwise have dropped the futures leg for up to 24h after deploy
- [x] Expiry compared as a full instant, not a date — the roll now happens at the contract's expiry time rather than at the following midnight

## Known Risks & Mitigation
| Risk | Mitigation |
|---|---|
| SDK bug or breaking change in `dhanhq` | Constrained to `>=2.0.0,<3.0.0` — an upper bound, not a pin, so patch/minor fixes flow in but a major rewrite of `MarketFeed` cannot land unreviewed. Tested against **2.2.0**. AEOLUS runs the same SDK, so defects surface in two places and are diagnosable |
| Scrip master unavailable at startup | `resolve_futures_security_id()` returns `None`; index legs still subscribe — degraded, not dead |
| Reconnect storm outside market hours | Exponential backoff to 60s; silence is not treated as an error |
| Token expiry mid-session | Credentials re-read from Redis on every reconnect attempt |
| `dhanhq` pulls a conflicting transitive `websockets` pin | Verified at install; `websockets` is already a direct dependency of the removed code path |
