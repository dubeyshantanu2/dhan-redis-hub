# Aeolus Readiness Audit — dhan-redis-hub

**Date:** 2026-07-28, 10:14–10:22 IST (market open, NIFTY spot ~23,985)
**Target:** `https://dhan-redis-hub.fly.dev` (Fly.io `bom`), repo @ `9681e16` (main)
**Scope:** Can the hub serve 100% of AEOLUS's real-time market data needs via `/expirylist`, `/optionchain`, `/quote`?

---

## Verdict

**Data coverage: 100%. Option chain + expiry already wired and correct. `/quote` is unwired — deliberately.**

Every field Aeolus needs is present and live. The hub is a **transparent proxy** returning Dhan v2 REST payloads verbatim (`poller.py` caches `resp.json()` unmodified), so field names are Dhan-REST-native, not the `dhanhq` WebSocket `Full`-packet names in the spec (`ltp`, `total_buy_quantity`, `bid_levels`).

**That mismatch is already handled where it matters.** Verified against the Aeolus repo (`~/Documents/Work/Aeolus`):

| Path | Status in Aeolus |
|---|---|
| `/expirylist` | ✅ wired — `redis_client.get_expiry_list()` → `feed_rest.resolve_nearest_expiry()` |
| `/optionchain` | ✅ wired **and correct** — `get_option_chain()` unwraps `data.oc`; `_parse_strike()` does `float(strike_str)` and maps `ce.oi→call_oi`, `ce.implied_volatility→call_iv`, `ce.greeks→call_greeks` |
| `/quote` | ⚠️ `redis_client.get_quote()` exists but has **zero callers** — returns the raw dict, no field mapping |

All quote-shaped fields (`futures_ltp`, `volume`, `total_buy_quantity`, `total_sell_quantity`, `day_high`, `day_low`, `depth.bid_levels`) come exclusively from the **direct Dhan WebSocket `Full` packet** in `feed_ws.py`. Aeolus does not route them through the hub.

**No hub change required.** See §4 — the remaining work is smaller than it first appears, and one part of it should probably not be done at all.

> **Bonus:** `feed_rest.py`'s module docstring flags the `data.oc[strike].ce/pe.{oi,implied_volatility,greeks}` nesting as *"provisional — confirm on first live run"*. **This audit is that confirmation.** The nesting is exactly as assumed. That caveat can be retired.

---

## 1. Endpoint liveness

Health: `{"status":"online","redis_connected":true,"auth_synced":true}`

| Endpoint | Live | Cached | Redis key | TTL |
|---|---|---|---|---|
| `POST /expirylist` | ✅ 200 | ✅ | `dhan:expirylist:{SYMBOL}` | 43200s (12h) |
| `POST /optionchain` | ✅ 200 | ✅ | `dhan:optionchain:{SYMBOL}:{expiry}` | 15s |
| `POST /quote` | ✅ 200 | ✅ | `dhan:quote:{security_id}` | 5s |

A background poller (`app.py:34`) pre-warms NIFTY / BANKNIFTY / FINNIFTY / SENSEX nearest-expiry chains on a ~10s loop, so Aeolus's primary NIFTY path is almost always a warm hit.

### 1a. `/expirylist` — exact spec match ✅

Request as specified returns a bare JSON array of `YYYY-MM-DD` strings. No adapter needed.

```json
["2026-07-28","2026-08-04","2026-08-11","2026-08-18","2026-08-25","2026-09-01",
 "2026-09-29","2026-12-29","2027-03-30", ... 18 total]
```

### 1b. `/optionchain` — data present, shape differs ⚠️

Spec expects `oc` at top level with flattened `call_oi` / `call_iv` / per-strike greeks.
Hub returns Dhan-native: wrapped in `data`, split per-leg (`ce` / `pe`), greeks nested.

238 strikes returned for `2026-07-28`; 158 KB payload.

```json
{"status":"success","data":{"last_price":23985.05,"oc":{
  "24000.000000":{
    "ce":{"oi":2678585,"implied_volatility":10.354,"last_price":185,"volume":12254710,
          "greeks":{"delta":0.44884,"theta":-41.35143,"gamma":0.00455,"vega":3.32586},
          "top_bid_price":184.6,"top_ask_price":185.1, ...},
    "pe":{"oi":16209765,"implied_volatility":12.440, "greeks":{...}, ...}}}}}
```

**Mapping:**

| Aeolus expects | Hub returns | Note |
|---|---|---|
| `oc` (top level) | `data.oc` | unwrap one level |
| strike key `"24000"` | `"24000.000000"` | 6-decimal string — parse as float, don't string-match |
| `call_oi` / `put_oi` | `oc[k].ce.oi` / `.pe.oi` | int ✅ |
| `call_iv` / `put_iv` | `oc[k].ce.implied_volatility` / `.pe…` | float ✅ |
| `delta`/`gamma`/`theta`/`vega` per strike | `oc[k].ce.greeks.*` **and** `.pe.greeks.*` | hub gives greeks **per leg** — richer than spec |

**Bonus fields not in the spec** (already there if wanted): `last_price`, `volume`, `previous_oi`, `previous_volume`, `average_price`, `top_bid_price/quantity`, `top_ask_price/quantity`, `security_id` per leg.

### 1c. `/quote` — full depth + volume confirmed ✅ (renamed fields)

Verified against three instruments during live market hours:

| Instrument | security_id | segment | Result |
|---|---|---|---|
| NIFTY JUL FUT | `61093` | `NSE_FNO` | ✅ full data |
| NIFTY AUG FUT | `58072` | `NSE_FNO` | ✅ full data |
| NIFTY Index | `13` | `IDX_I` | ✅ price/OHLC; depth & volume are structurally zero |
| India VIX | `21` | `IDX_I` | ✅ price/OHLC; depth & volume are structurally zero |

⚠️ **`exchange_segment` for indices must be `IDX_I`, not `NSE_FNO`.** The spec's example payload uses `NSE_FNO` for all three — that is correct for futures only.

Live NIFTY JUL FUT (`61093`) response, abbreviated:

```json
{"last_price":23987,"volume":828685,"buy_quantity":74555,"sell_quantity":233610,
 "ohlc":{"open":23998,"close":24028,"high":24038,"low":23962.3},
 "oi":7324720,"oi_day_high":7835685,"oi_day_low":7324720,
 "average_price":24011.32,"last_quantity":65,"last_trade_time":"28/07/2026 10:15:22",
 "upper_circuit_limit":26430.8,"lower_circuit_limit":21625.2,
 "depth":{
   "buy":[{"price":23985,"quantity":195,"orders":1},{"price":23984.9,"quantity":65,"orders":1},
          {"price":23984.8,"quantity":325,"orders":1},{"price":23984.7,"quantity":130,"orders":2},
          {"price":23984.5,"quantity":260,"orders":4}],
   "sell":[{"price":23987,"quantity":1690,"orders":1},{"price":23988,"quantity":1755,"orders":1},
           {"price":23988.7,"quantity":65,"orders":1},{"price":23988.9,"quantity":130,"orders":2},
           {"price":23990,"quantity":325,"orders":5}]}}
```

**Mapping:**

| Aeolus expects | Hub returns | Type |
|---|---|---|
| `ltp` | `last_price` | float ✅ |
| `volume` | `volume` | int ✅ **exact match** |
| `total_buy_quantity` | `buy_quantity` | int ✅ |
| `total_sell_quantity` | `sell_quantity` | int ✅ |
| `day_high` | `ohlc.high` | float ✅ |
| `day_low` | `ohlc.low` | float ✅ |
| `depth.bid_levels[]` | `depth.buy[]` | 5 levels ✅ |
| `depth.ask_levels[]` | `depth.sell[]` | 5 levels ✅ |
| level `{price, quantity}` | `{price, quantity, orders}` | superset ✅ |

`ohlc.high`/`ohlc.low` are session price extremes — **not** `oi_day_high`/`oi_day_low`, which track OI extremes. Same distinction Aeolus already documented for the WS `Full` packet ([[12_Module_Order_Flow]]).

---

## 2. Latency

Measured from a local Mac over public internet to Fly `bom`. **Baseline RTT to `GET /` (no cache, ~60 B): min 341 / med 452 / max 1039 ms** — network dominates every number below. Subtract it to read server-side cost.

| Endpoint | Warm (cache HIT) med | vs. RTT | True cold MISS |
|---|---|---|---|
| `/expirylist` | **371 ms** (min 359, max 471) | ~0 ms | 379 ms |
| `/quote` | **412 ms** (min 361, max 711) | ~0 ms | **3059 ms** |
| `/optionchain` | **1094 ms** (min 838, max 1404) | ~+650 ms | 689 – 1954 ms |

**Reading these:**
- `/quote` and `/expirylist` cache hits are **indistinguishable from bare network RTT** — Redis serve cost is under measurement noise (<50 ms).
- `/optionchain`'s ~650 ms premium is **payload transfer, not cache lookup** — 158 KB for 238 strikes over a home link.
- **Cold-miss `/quote` at 3.06 s is the RateGovernor**, not Dhan. `rate_limit_quote_secs = 1.5` plus a 1.25 s global spacing (`governor.py`) serialises every upstream call. Any Aeolus instrument outside the pre-warmed universe pays this on first touch and every 5 s thereafter once its TTL expires.
- Cold-miss `/optionchain` measured on **un-polled** far expiries (`2026-12-29`, `2027-03-30`) to defeat the background poller. NIFTY nearest-expiry is effectively never cold for Aeolus.

**If Aeolus deploys to Fly `bom`**, intra-region latency replaces the ~350 ms RTT entirely — expect single-digit-ms warm reads and ~30 ms for the 158 KB chain.

---

## 3. Answers to the three questions

**Q1 — All 3 endpoints live and cached in Redis?**
Yes. All three return HTTP 200 with `redis_connected: true`, backed by explicit Redis keys and TTLs (12 h / 15 s / 5 s). NIFTY's chain and expiry list are additionally pre-warmed by the background poller.

**Q2 — Average response latency?**
`/quote` **~412 ms** warm, `/optionchain` **~1094 ms** warm, measured over public internet where **~350 ms is pure RTT**. Server-side cache serve is effectively free; the option chain's extra ~650 ms is 158 KB of transfer. Cold `/quote` misses hit **~3 s** because of RateGovernor serialisation — the one real latency risk for Aeolus.

**Q3 — Is `/quote` supplying full 5-level depth and cumulative session volume for NIFTY Futures?**
**Yes, confirmed live.** NIFTY JUL FUT (`61093`) returned all 5 bid and all 5 ask levels with non-zero price/quantity/orders, plus `volume: 828685` cumulative session volume and `buy_quantity`/`sell_quantity` totals. Same for NIFTY AUG FUT (`58072`). Field names are `depth.buy` / `depth.sell`, not `bid_levels` / `ask_levels`.

---

## 4. What actually needs doing

**1. Nothing, for the option chain and expiry list.** Both are wired, mapped, and — as of this audit — live-verified. `feed_rest.py`'s "provisional nesting" caveat is now confirmed and can be deleted.

**2. Don't wire `/quote` into the hot path — migrate AEOLUS's WebSocket to the hub's Pub/Sub instead.** Routing the futures leg through REST `/quote` would be a downgrade (5 s TTL plus up to ~3 s of RateGovernor wait on a cold miss, versus tick-level freshness). Tick-level data should stay tick-level.

> **Superseded by TASK-006 (2026-07-28).** At audit time the hub's own WebSocket published nothing, so AEOLUS's direct Dhan connection was the only way to get depth and volume. That pipeline is now repaired and verified live at ~10 ticks/s across 5 instruments, futures `Full` packets included — see `reports/debug/TASK-006_debug-report.md`.
>
> AEOLUS's `feed_ws.py` should now swap `dhanhq.MarketFeed` for `client.subscribe_ticks()` on `dhan:ticks:<id>`. The hub republishes the SDK dict **verbatim**, so `_on_message()` and `_parse_depth()` work unchanged — it is a transport swap, not a re-model. That removes the last direct `api.dhan.co` connection from AEOLUS and restores the hub's single-fetcher guarantee.
>
> `redis_client.get_quote()` remains unmapped dead code. Either add the rename map from §1c and use it as the WS-drop fallback, or delete it.

**3. Indices need `IDX_I`, not `NSE_FNO`.** NIFTY Index = `13`, India VIX = `21`. Their `depth`, `volume`, `buy_quantity`, `sell_quantity` are all structurally `0` — indices don't trade. Aeolus must not treat these zeros as a data fault. `last_price` and `ohlc` are valid.

**4. Sparse greeks on illiquid strikes (upstream Dhan behaviour — affects GEX). The one real correctness bug this audit found.** Dhan returns `greeks: {delta:0,gamma:0,theta:0,vega:0}` and `implied_volatility: 0` for strikes without a recent trade. Reproduced on both `2026-07-28` and `2026-08-04`: **14–17 of 48 strikes within ±5% of spot** have a zeroed leg. Some carry real open interest — strike 23000 CE had `oi: 121615` with `gamma: 0`.

> This is not a hub defect and no hub change fixes it. But `net_gamma_at_strike = call_gamma * call_oi − put_gamma * put_oi` ([[10_Module_Gamma]]) silently contributes **zero** for those strikes, systematically under-counting ITM gamma with no error raised. Aeolus should either compute greeks locally from IV/spot/strike/tenor when Dhan returns 0-with-OI, or explicitly exclude and log those strikes.

**5. Single-instance rate governor is a hard throughput ceiling.** `fly.toml` pins `min_machines_running = 1` and the governor is in-process — correct for quota safety, but it means every un-cached Aeolus request serialises behind ~1.25–2.5 s spacing. Stay inside the pre-warmed universe (NIFTY / BANKNIFTY / FINNIFTY / SENSEX nearest expiry) for real-time paths.

## Not gaps

- Payload contracts in the spec are accepted exactly as written (`underlying_scrip`, `underlying_seg`, `symbol`, `expiry`, `security_id`, `exchange_segment`) — `app.py:103-116`.
- `/expirylist` needs no adapter at all.
- Strike keys arrive as `"24000.000000"`, but `feed_rest._parse_strike()` already does `float(strike_str)` — handled.
- Depth levels carry an extra `orders` field — superset of spec, harmless.

---

## Bottom line

The hub **can** serve 100% of Aeolus's requirements, and **already serves** the two paths Aeolus routes through it. The third (`/quote`) is proven capable but intentionally bypassed in favour of the lower-latency WebSocket — that is the correct architecture, not a gap.

The only item worth acting on is the **sparse-greeks GEX under-count** (§4.4), and it is an upstream Dhan data characteristic, fixable only on the Aeolus side.
