# Debug Report — TASK-006
**Date:** 2026-07-28
**Verdict:** ✅ CLEAN

## Test Environment
Full local stack, live market hours (NIFTY spot ~23,998):
- Redis 8.x on `localhost:6379` (Homebrew)
- `uvicorn app:app` on `127.0.0.1:8000`
- Real Supabase credential sync → real Dhan v2 REST + WebSocket

## Verification

### 1. Startup & credential sync
```
auth_sync: Successfully synced Dhan credentials for client ID: 11******82 into Redis.
GET / → {"status":"online","redis_connected":true,"auth_synced":true}
```

### 2. Futures leg auto-resolution ✅
```
ws_feed: Resolved NIFTY futures leg: security_id=61093 (expiry 2026-07-28 14:30:00)
ws_feed: Connecting Dhan WebSocket feed (5 instruments)...
ws_feed: Dhan WebSocket Hub connected.
```
Resolved from the cached scrip master with no hardcoded ID. Correctly selected the JUL contract over AUG/SEP, and did not match NIFTYNXT50.

### 3. Ticks published ✅ (the defect this task exists to fix)
20-second Pub/Sub capture via `psubscribe dhan:ticks:*`:

| Channel | Instrument | Ticks | Rate |
|---|---|---|---|
| `dhan:ticks:13` | NIFTY spot | 80 | 4.0/s |
| `dhan:ticks:25` | BANKNIFTY | 81 | 4.0/s |
| `dhan:ticks:61093` | NIFTY JUL FUT | 26 | 1.3/s |
| `dhan:ticks:27` | FINNIFTY | 7 | 0.3/s |
| `dhan:ticks:21` | India VIX | 2 | 0.1/s |
| **Total** | | **196** | **~10/s** |

Pre-fix baseline was **0 ticks, permanently**.

### 4. Futures Full packet carries required fields ✅
`dhan:tick:61093`:
```json
{"type":"Full Data","security_id":61093,"LTP":"23998.10","volume":1130220,
 "total_buy_quantity":75465,"total_sell_quantity":236665,
 "high":"24038.00","low":"23962.30","OI":7356895,
 "depth":[ ...5 levels, each {bid_price,bid_quantity,bid_orders,ask_price,ask_quantity,ask_orders} ]}
```
All 7 required fields present. Depth array length = 5.

### 5. Key-collision regression check ✅
```
redis-cli --scan --pattern 'dhan:quote:*' | wc -l  →  0
```
The WS path writes only `dhan:tick:*`. `/quote` response keys confirmed still Dhan-REST-shaped (`last_price`, `ohlc`, `depth.buy`), with no WS field names (`LTP`, `total_buy_quantity`) leaking in.

### 6. REST endpoint regression ✅
| Endpoint | Result |
|---|---|
| `/expirylist` | 18 expiries |
| `/optionchain` | 238 strikes |
| `/quote` | REST shape intact, WS shape absent |

## Bugs Found
None in TASK-006 scope.

## Out-of-Scope Issue Observed (not fixed)
**`python-dotenv` is a declared dependency but never called.** No `load_dotenv()` exists anywhere in the codebase, so the README's documented local-run flow (`cp .env.example .env` → edit → `uvicorn app:app`) silently ignores `.env` and starts with no Supabase credentials. Worked around during this test by exporting the vars via `set -a; source .env`. Deployed environments are unaffected (Fly secrets and docker-compose inject real env vars). Reported, not fixed — outside the ADR.

## Notes
- Initial smoke attempt using `dhan-auth-sync/.env` failed with HTTP 401: that token is stale. The token in Supabase is current and was used instead. This was a harness credential issue, not a code defect.
- Outside market hours the feed is legitimately silent; this run was during live hours so silence was not a confounder.
