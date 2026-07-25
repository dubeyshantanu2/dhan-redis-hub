# Changelog — Dhan Redis Hub

All notable changes to the `dhan-redis-hub` project will be documented in this file.

## [1.0.0] - 2026-07-25

### Added
- **Authentication Sync (`auth_sync.py`)**: Automatic credential loader fetching active tokens from Supabase `api_keys` into Redis `dhan:auth`.
- **Async Rate Governor (`governor.py`)**: Token-bucket throttle with exponential backoff on HTTP 429 errors.
- **Background Poller & Caching (`poller.py`)**: Fetcher for option chains, expiry lists, market quotes, and historical OHLCV candles with configurable TTLs.
- **Single WebSocket Hub (`ws_feed.py`)**: Centralized WebSocket connection to `wss://api-feed.dhan.co` broadcasting tick packets to Redis Pub/Sub channels (`dhan:ticks:<security_id>`).
- **Client SDK (`client.py`)**: `DhanRedisClient` Python module for trading engines to read cached data in < 1ms.
- **FastAPI Proxy Server (`app.py`)**: REST endpoints for health check, manual credential sync, and cache miss proxying.
- **Docker Setup (`docker-compose.yml`, `Dockerfile`)**: Containerized environment for local or cloud deployment.
- **Documentation**: Comprehensive PRD, Software Architecture spec, ADR-001, and README.
