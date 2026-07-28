# Software Architecture Document — Dhan Redis Hub (`dhan-redis-hub`)

**Author:** Software Architect Agent  
**Status:** Approved  
**Version:** 1.0.0  
**Date:** 2026-07-25  

---

## 1. System Topology & Component Diagram

```
+-----------------------------------------------------------------------------------+
|                                  DHAN API v2                                      |
|                       https://api.dhan.co / wss://api-feed.dhan.co                |
+-----------------------------------------------------------------------------------+
                                         ^
                                         | Governed REST / 1 WebSocket Feed
                                         v
+-----------------------------------------------------------------------------------+
|                        dhan-redis-hub (Central Service)                           |
|  ┌──────────────────┐    ┌──────────────────┐    ┌─────────────────────────────┐  |
|  │  auth_sync.py    │    │   governor.py    │    │          poller.py          │  |
|  │ (Supabase Sync)  │    │  (Rate Governor) │    │  (Option Chains/Quotes/OHLC)│  |
|  └──────────────────┘    └──────────────────┘    └─────────────────────────────┘  |
|  ┌──────────────────┐    ┌──────────────────┐                                     |
|  │    ws_feed.py    │    │      app.py      │                                     |
|  │ (WebSocket Feed) │    │  (FastAPI Proxy) │                                     |
|  └──────────────────┘    └──────────────────┘                                     |
+-----------------------------------------------------------------------------------+
                                         |
                                         v Writes / Publishes
+-----------------------------------------------------------------------------------+
|                             REDIS IN-MEMORY CACHE                                 |
|  - Key: dhan:auth                              (String / JSON)                     |
|  - Key: dhan:optionchain:{symbol}:{expiry}     (String / JSON, TTL: 2s)            |
|  - Key: dhan:expirylist:{symbol}               (String / JSON, TTL: 12h)           |
|  - Key: dhan:quote:{security_id}               (String / JSON, TTL: 5s)            |
|  - Key: dhan:candles:{security_id}:{int}:{dates}(String / JSON, TTL: 15m/24h)        |
|  - Key: dhan:tick:{security_id}                (String / JSON, TTL: 60s)           |
|  - PubSub: dhan:ticks:{security_id}            (Real-time Channel)                 |
+-----------------------------------------------------------------------------------+
          ^                          ^                          ^
          │                          │                          │ Reads Cache / PubSub
          ▼                          ▼                          ▼
┌──────────────────┐       ┌──────────────────┐       ┌──────────────────┐
│   ARES Engine    │       │ gamma-blaster    │       │  Kronos Engine   │
└──────────────────┘       └──────────────────┘       └──────────────────┘
```

---

## 2. Redis Data Schema Reference

| Redis Key Pattern | Type | Expiry (TTL) | Payload Description |
|---|---|---|---|
| `dhan:auth` | String (JSON) | 12 hours | `{ "client_id": "...", "access_token": "...", "updated_at": "..." }` |
| `dhan:optionchain:{symbol}:{expiry}` | String (JSON) | 2s (Market) / 60s (Off-Market) | Complete raw Option Chain JSON response from Dhan API |
| `dhan:expirylist:{symbol}` | String (JSON) | 12 hours | Array of expiry date strings `["2026-07-30", ...]` |
| `dhan:quote:{security_id}` | String (JSON) | 5 seconds | Market quote dictionary (`ltp`, `open`, `high`, `low`, `volume`, `oi`) |
| `dhan:candles:{security_id}:{interval}:{from}:{to}` | String (JSON) | 15m (intraday) / 24h (daily) | Historical OHLCV candle arrays |
| `dhan:tick:{security_id}` | String (JSON) | 60 seconds | Last-tick snapshot, so a subscriber connecting between ticks has a starting value. Same payload as the Pub/Sub channel below. **Distinct from `dhan:quote:` on purpose** — that key carries Dhan *REST* field names, this one carries *WebSocket* names |
| `dhan:ticks:{security_id}` | Pub/Sub Channel | Real-time | Live tick packet, published verbatim from `dhanhq.MarketFeed`. Indices (`Ticker Data`): `{type, exchange_segment, security_id, LTP, LTT}`. Futures (`Full Data`): adds `volume`, `total_buy_quantity`, `total_sell_quantity`, `OI`, `open`/`close`/`high`/`low`, and `depth[]` — 5 levels of `{bid_price, bid_quantity, bid_orders, ask_price, ask_quantity, ask_orders}` |

### WebSocket Subscription Universe

One WSS connection per machine (`min_machines_running = 1` guarantees exactly one). Indices subscribe at `Ticker`; futures legs at `Full`, the only v2 mode bundling 5-level depth with LTP, volume, and OI in a single packet.

| Instrument | security_id | Segment | Mode |
|---|---|---|---|
| NIFTY spot | `13` | `IDX` | Ticker |
| India VIX | `21` | `IDX` | Ticker |
| BANKNIFTY | `25` | `IDX` | Ticker |
| FINNIFTY | `27` | `IDX` | Ticker |
| NIFTY current-month FUT | *resolved at runtime* | `NSE_FNO` | Full |

The futures contract ID is resolved from the cached scrip master by `ws_feed.resolve_futures_security_id()`, so the monthly roll requires no config change. Configure additional futures legs via `WS_FUTURES_SYMBOLS` (comma-separated).

> **Consumers must read ticks from Pub/Sub, not open their own Dhan WebSocket.** A direct client connection defeats the hub's single-fetcher guarantee and counts against the same Dhan connection quota.

---

## 3. Data Flow & Sequence Diagram

### Read Flow (Trading Engine Requests Option Chain)

```
Client Bot (e.g. ARES)       DhanRedisClient             Redis Cache             dhan-redis-hub             Dhan API v2
         │                         │                          │                         │                        │
         │── get_option_chain() ──>│                          │                         │                        │
         │                         │── GET dhan:optionchain ─>│                         │                        │
         │                         │                          │                         │                        │
         │                         │<─── Cache HIT (JSON) ────│                         │                        │
         │<── Return Data (<1ms) ──│                          │                         │                        │
         │                         │                          │                         │                        │
         │                         │─ (If Cache MISS) ────────┼────────────────────────>│                        │
         │                         │                          │                         │─ RateGovernor Wait ───>│
         │                         │                          │                         │── POST /v2/optionchain>│
         │                         │                          │                         │<─ Response (200 OK) ───│
         │                         │                          │<── SET key with TTL ────│                        │
         │<── Return Data ─────────│<── Return Proxy Response ┼─────────────────────────│                        │
```

---

## 4. Rate Limiting Strategy (Token-Bucket)

The `RateGovernor` ([governor.py](file:///Users/manmadeanyme/Documents/Work/dhan-redis-hub/governor.py)) maintains an in-process timestamp lookup table per endpoint category:
- `optionchain`: 1.0 second minimum interval.
- `quote`: 0.5 second minimum interval.
- `candles`: 1.0 second minimum interval.

If HTTP status 429 occurs, `RateGovernor` applies exponential backoff:
$$\text{Backoff Time} = \text{base\_backoff} \times 2^{(\text{attempt} - 1)}$$

---

## 5. Deployment Options

1. **Local Development**: Docker Compose (`redis:7-alpine` + `dhan-redis-hub` container).
2. **Cloud Deployment (Fly.io / VPS)**:
   - Deploy `dhan-redis-hub` to Fly.io (`bom` region, Mumbai) or Render/Railway/VPS.
   - Connect to Upstash Redis or standalone Redis container.
