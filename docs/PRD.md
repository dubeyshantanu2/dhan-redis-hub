# Product Requirement Document (PRD) — Dhan Redis Hub (`dhan-redis-hub`)

**Author:** Software Architect Agent / Product Manager Agent  
**Status:** Approved  
**Version:** 1.0.0  
**Date:** 2026-07-25  

---

## 1. Executive Summary & Problem Statement

### Problem
Multiple independent trading systems (**ARES**, **Aeolus**, **Argus**, **gamma-blaster**, **Kronos**, **stock-screener**) run concurrently during Indian stock market hours (9:15 AM – 3:30 PM IST). Each system generates individual HTTP REST requests and WebSocket connections to the Dhan API (`https://api.dhan.co/v2`) under the same client credentials.

Because each system operates without awareness of other running applications, aggregate request volumes violate Dhan's rate limits, producing **HTTP 429 (Too Many Requests)** errors. This causes signal drops, execution failures, and system instability.

### Goal
Centralize all Dhan API data fetching through a single-instance proxy and memory cache service (**`dhan-redis-hub`**) using Redis. Eliminate 429 rate limit errors completely by ensuring only one service communicates with Dhan API at governed request frequencies, serving all client trading systems from high-speed in-memory cache.

---

## 2. Product Requirements & Features

### FR-1: Single-Fetcher Architecture
- **Requirement:** Only `dhan-redis-hub` shall issue REST requests to `api.dhan.co`. Individual trading applications MUST NOT call Dhan API directly.
- **Priority:** High (P0)

### FR-2: Centralized Rate Governor
- **Requirement:** `dhan-redis-hub` MUST implement an async token-bucket rate governor enforcing minimum intervals per endpoint type (Option Chains: 1.0s, Quotes: 0.5s, Candles: 1.0s).
- **Priority:** High (P0)

### FR-3: Supabase Authentication Sync
- **Requirement:** `dhan-redis-hub` MUST automatically fetch and synchronize active Dhan access tokens from the shared Supabase `api_keys` table into Redis key `dhan:auth`.
- **Priority:** High (P0)

### FR-4: Proactive Caching & TTL Management
- **Requirement:** All responses fetched from Dhan API must be cached in Redis with configurable Time-To-Live (TTL):
  - Option Chains: 2 seconds (market hours) / 60 seconds (off-market).
  - Quotes / LTP: 5 seconds.
  - Expiry Lists: 12 hours.
  - Historical Candles: 15 minutes (intraday) / 24 hours (daily).
- **Priority:** High (P0)

### FR-5: Single WebSocket Feed & Pub/Sub
- **Requirement:** `dhan-redis-hub` MUST maintain a single WebSocket connection (`wss://api-feed.dhan.co`) and broadcast real-time tick events to Redis Pub/Sub channel `dhan:ticks:<security_id>`.
- **Priority:** Medium (P1)

### FR-6: Lightweight Client SDK (`DhanRedisClient`)
- **Requirement:** Provide a lightweight Python adapter module (`client.py`) for trading bots to query Redis cache directly with sub-millisecond latency.
- **Priority:** High (P0)

---

## 3. Non-Functional Requirements (NFRs)

- **Latency:** Redis cache hits must return data in **< 2 milliseconds**.
- **Reliability:** 99.9% uptime during market hours (9:00 AM – 4:00 PM IST).
- **Security:** Credentials stored in Redis must be protected via environment configuration and bounded network access.
- **Portability:** Containerized via Docker / Docker Compose for deployment locally, on Fly.io, Render, Railway, or VPS.

---

## 4. Success Metrics

1. **Zero 429 Rate Limit Errors** across all trading applications.
2. **> 95% Cache Hit Ratio** for NIFTY/BANKNIFTY option chains and market quotes during market hours.
3. **Sub-millisecond data retrieval latency** for downstream trading engines.
