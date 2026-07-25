# ADR-001: Centralized Dhan API Proxy and In-Memory Cache via Redis

**Status:** Accepted  
**Date:** 2026-07-25  
**Deciders:** Software Architect Agent, PM Agent, Human Lead  

---

## 1. Context and Problem Statement

Multiple trading applications (**ARES**, **Aeolus**, **Argus**, **gamma-blaster**, **Kronos**, **stock-screener**) independently execute REST API requests and open WebSocket connections to the Dhan API (`https://api.dhan.co/v2`). 

Each project maintained its own isolated rate governor. Because these projects ran concurrently without inter-process coordination, their combined request rates violated Dhan's per-account rate limits, producing **HTTP 429 (Too Many Requests)** errors and failing live trading operations.

---

## 2. Decision Rationale

We decided to establish a **Single Writer / Centralized Cache Architecture** using Redis:

1. **Centralized Service (`dhan-redis-hub`)**: A single-instance worker and proxy service that owns all outbound communication with `api.dhan.co`.
2. **In-Memory Cache (Redis)**: Short-lived cached records (2s TTL for option chains, 5s for quotes, 12h for expiries) allowing downstream bots to query market data with **< 1ms latency**.
3. **Async Rate Governor**: An internal token-bucket governor enforcing strict per-endpoint intervals before issuing HTTP requests to Dhan.
4. **Supabase Credential Integration**: Automatic loading of active credentials from Supabase `api_keys` (managed by `dhan-auth-sync`).

---

## 3. Alternatives Considered

### Alternative A: Peer-to-Peer Rate Limiting via Redis Locks
- **Description:** Allow each bot to hit Dhan directly, but coordinate rate limit windows using Redis locks (`redlock`).
- **Why Rejected:** Complex to handle network failures, leaves multiple WebSocket feeds open, and risks lock deadlocks across multiple projects.

### Alternative B: Direct Supabase Caching
- **Description:** Cache Option Chains and Quotes in Supabase PostgreSQL tables instead of Redis.
- **Why Rejected:** High database write load and latency (~50ms SQL query vs ~0.5ms Redis lookup). PostgreSQL is built for persistent storage, not high-frequency market tick buffers.

---

## 4. Consequences

### Positive:
- **Zero 429 Errors:** Dhan API receives at most 1 request per second.
- **Sub-millisecond Performance:** Downstream bots read option chains and quotes instantly from RAM.
- **Reduced Bandwidth:** 1 single WebSocket feed instead of 5+ duplicate feeds.

### Negative / Trade-offs:
- Introduces `dhan-redis-hub` as a single point of failure (mitigated by health checks and auto-restart policies).
