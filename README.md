# Dhan Redis Hub (`dhan-redis-hub`)

Centralized Redis Caching, Pub/Sub, and Rate Governance service for Dhan API v2.

## Problem Solved
When multiple trading systems (`ARES`, `Aeolus`, `gamma-blaster`, `Kronos`, `stock-screener`, `Argus`) run concurrently, they make redundant requests to Dhan API endpoints (Option Chains, Quotes, Candles, Expiries). Because each bot operates independently, aggregate request rates exceed Dhan's limits and return **429 (Too Many Requests)** errors.

`dhan-redis-hub` acts as a **Single Fetcher & Central Cache**:
1. Only `dhan-redis-hub` communicates with `api.dhan.co`.
2. All requests to Dhan API pass through an internal async **RateGovernor** (token-bucket pattern) with exponential backoff on 429s.
3. Responses (Option Chains, Quotes, Expiries, Candles, Scrip Master) are stored in Redis with short TTLs (e.g. 2s for market option chains).
4. Live price ticks from Dhan's WebSocket feed are broadcast over **Redis Pub/Sub** (`dhan:ticks:<security_id>`).
5. Client applications read from Redis with sub-millisecond latency using the lightweight `DhanRedisClient` library.

---

## Quick Start

### 1. Run via Docker Compose (Recommended)
```bash
docker-compose up -d
```
This spins up:
- **Redis Server** on port `6379`.
- **Dhan Redis Hub Service** on port `8000`.

### 2. Manual Python Execution
```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your SUPABASE_URL and SUPABASE_KEY
uvicorn app:app --host 0.0.0.0 --port 8000
```

---

## Using `DhanRedisClient` in Projects (`ARES`, `gamma-blaster`, `Kronos`, etc.)

Copy `client.py` into your project or import `DhanRedisClient`:

```python
from client import DhanRedisClient

client = DhanRedisClient(redis_host="localhost", redis_port=6379, project_name="Kronos")  # project_name tags hub-side error logs and alerts

# 1. Fetch Option Chain (Sub-millisecond Redis Cache Hit!)
option_chain = client.get_option_chain(symbol="NIFTY", expiry="2026-07-30")

# 2. Fetch Latest Quote
quote = client.get_quote(security_id=13)

# 3. Subscribe to Real-Time Ticks (Redis Pub/Sub)
def on_tick(tick_data):
    print("New tick received:", tick_data)

client.subscribe_ticks(security_id=13, callback=on_tick)
```

---

## Redis Data Schema

| Key Pattern | Type | TTL | Purpose |
|---|---|---|---|
| `dhan:auth` | String (JSON) | 12h | Active credentials (`client_id`, `access_token`) synced from Supabase |
| `dhan:optionchain:{symbol}:{expiry}` | String (JSON) | 2s | Cached option chain payload |
| `dhan:expirylist:{symbol}` | String (JSON) | 12h | Available expiries list |
| `dhan:quote:{security_id}` | String (JSON) | 5s | Latest market quote & LTP |
| `dhan:candles:{security_id}:{interval}:{from}:{to}` | String (JSON) | 15m / 24h | Historical OHLCV candles |
| `dhan:ticks:{security_id}` | Pub/Sub | Real-time | Live WebSocket tick broadcast channel |
