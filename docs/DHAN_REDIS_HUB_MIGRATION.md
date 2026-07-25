# Dhan Redis Hub — Centralized Migration Guide & Project Checklist

> **Context for AI Agents & Developers:**
> During Indian market hours (9:15 AM – 3:30 PM IST), multiple trading engines (**ARES**, **Aeolus**, **Argus**, **gamma-blaster**, **Kronos**, **stock-screener**, **Kairos**) run concurrently.
> Making direct HTTP calls to `api.dhan.co/v2` from each service breaches Dhan's strict rate limits (1 req/sec per endpoint category) and causes HTTP 429 errors.
>
> **The Solution:**
> **`dhan-redis-hub`** is a central microservice and embedded Redis cache deployed on Fly.io Mumbai (`https://dhan-redis-hub.fly.dev`).
> It governs outbound calls via an async `RateGovernor`, caches market payloads in Redis (option chains, expiry lists, quotes, candles, scrip master), and serves all trading bots via `<1ms` Redis reads or HTTP proxy calls.

---

## Migration Checklist

- [x] **Kronos** — Completed (2026-07-25 / PR #24 & PR #25)
- [ ] **ARES** — Pending Migration
- [ ] **Aeolus** — Pending Migration
- [ ] **Argus** — Pending Migration
- [ ] **gamma-blaster** — Pending Migration
- [ ] **stock-screener** — Pending Migration
- [ ] **Kairos** — Pending Migration

---

## Instructions for AI Agents Performing Project Migrations

When assigned to migrate any project to `dhan-redis-hub`, follow these exact steps:

### Step 1: Add Client Module (`dhan_redis_client.py`)
Copy `dhan_redis_client.py` into the target project's fetcher package (e.g. `src/fetcher/dhan_redis_client.py` or `fetcher/dhan_redis_client.py`).

Key methods available in `DhanRedisClient`:
- `get_auth()` — Returns valid Dhan credentials (synced from Supabase `api_keys`).
- `get_scrip_master()` — Returns cached Dhan Compact Scrip Master CSV dict.
- `get_option_chain(symbol, underlying_scrip, underlying_seg, expiry)` — Returns option chain dict.
- `get_expiry_list(symbol, underlying_scrip, underlying_seg)` — Returns list of expiry dates.
- `get_quote(security_id, exchange_segment)` — Returns market quote dict.
- `get_quotes_batch(ids_by_segment)` — Batch Redis `MGET` quote lookup (<1ms).
- `get_candles(security_id, exchange_segment, instrument_type, interval, from_date, to_date)` — Returns historical OHLCV candles dict.

### Step 2: Update Project Configuration (`settings.yaml` / `config.py`)
Add Dhan Redis Hub settings to the project configuration:
```yaml
dhan:
  use_redis_hub: true
  hub_url: "https://dhan-redis-hub.fly.dev"
  redis_host: "localhost"
  redis_port: 6379
```

### Step 3: Wrap Existing Dhan API Client
Update the target project's Dhan client (e.g., `DhanClient`):
1. Initialize `self.redis_client = DhanRedisClient(hub_url=..., timeout=30.0)` if `use_redis_hub` is enabled.
2. In `option_chain()`, `expiry_list()`, `quotes()`, `historical_daily()`, check `self.redis_client` first.
3. Keep automated fallback to direct Dhan REST API (`_post`) only if `self.redis_client` returns `None` (offline safety guard).

### Step 4: Verification & Zero-Fallback Audit
1. Run local test suite (`pytest`).
2. Run live verification script asserting that `dhan-redis-hub` serves requests without triggering direct REST fallbacks.
3. Follow Global Development Pipeline: create a feature branch (`feature/...`), update `CHANGELOG.md`, push branch, and open PR via `gh pr create`. Do NOT merge PR directly.
4. Mark project as completed (`[x]`) in this checklist after user merges PR.
