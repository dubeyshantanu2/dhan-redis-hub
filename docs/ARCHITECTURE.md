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
| `dhan:ticks:{security_id}` | Pub/Sub Channel | Real-time | Live tick broadcast packet `{ "security_id": 13, "LTP": 24500.5 }` |

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
