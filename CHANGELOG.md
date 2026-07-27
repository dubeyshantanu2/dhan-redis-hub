# Changelog

All notable changes to `dhan-redis-hub`.

## [1.4.0] - 2026-07-27

### Fixed
- **Poller Rate Governance & 429 Prevention (TASK-429)**:
  - Added `await asyncio.sleep(1.0)` between index iterations in `background_universe_poller()` to eliminate rapid request bursts to Dhan API.
  - Increased post-pass poller loop sleep from `2.0s` to `5.0s`.
  - Guaranteed `dhan:expirylist:<SYMBOL>` caching with 12-hour TTL (`ex=43200`) in `poller.py` `fetch_and_cache_expiry_list()`.
  - Included `SENSEX` (`underlying_id: 12`) in default indices configuration.
  - Added unit test suite in `tests/test_redis_hub.py` for expiry list 12h TTL caching and poller delays (10/10 pytest suite passing).

## [1.3.0] - 2026-07-26

### Added
- **3-Tier Discord System Health Alert Logging System (`alerts.py`)**:
  - `send_startup_alert()`: Posts green initialization status block to Discord on launch (Status, Fly Region, Redis connectivity, Dhan Auth status, Rate Governor status).
  - `send_error_alert()`: Real-time alert system notifying Discord on Redis disconnects, HTTP 429 rate limit backoffs, and background poller exceptions.
  - `send_shutdown_alert()`: Fired on service shutdown / machine restart posting offline status block.
  - Configured `DISCORD_HEALTH_WEBHOOK_URL` secret on Fly.io production machine.
  - Added unit test suite in `tests/test_alerts.py` (6/6 pytest suite passing).
- **Comprehensive Environment Template (`example.env` / `.env.example`)**:
  - Documented all 19 environment variables used across Redis cache, Supabase auth sync, Discord health webhooks, Dhan API endpoints, Rate Governor thresholds, and TTL configurations.

## [1.2.0] - 2026-07-26

### Added
- **GitHub Actions Continuous Deployment Workflow (`.github/workflows/fly-deploy.yml`)**:
  - Configured automated test & deploy pipeline that triggers on merge to `main`.
  - Runs unit tests via `pytest` before deploying to Fly.io Mumbai (`bom`) region using `FLY_API_TOKEN` secret.
  - Added `pytest.ini` with `pythonpath = .` for clean test imports.
- **Migration Guide & Project Checklist (`docs/DHAN_REDIS_HUB_MIGRATION.md`)**:
  - Added comprehensive AI Agent context and 4-step migration guide.
  - Added multi-project migration checklist (Kronos [x], ARES [ ], Aeolus [ ], Argus [ ], gamma-blaster [ ], stock-screener [ ], Kairos [ ]).
  - Synced to Obsidian Vault at `~/Documents/Obsidian/Trading Methodology/Dhan Redis Hub Migration Guide.md`.

## [1.1.0] - 2026-07-26

### Fixed
- **Empty Payload & Quote Nesting Fix (PR #1 & PR #2)**:
  - Fixed boolean check `if not data:` to `if data is None:` in `app.py` so empty payloads off-market hours return valid status HTTP 200 instead of HTTP 502 Bad Gateway.
  - Updated `fetch_and_cache_quote` in `poller.py` to extract quotes through segment nesting (`raw_data[exchange_segment][security_id]`) and require non-empty dictionary payload before caching.
  - Broadened option chain payload validation in `poller.py` to recognize `oc`, `last_price`, and `data` structures.
  - Increased HTTP client timeout to 30.0s for cold option chain queries.

## [1.0.0] - 2026-07-25

### Added
- **Initial Microservice Release**:
  - Embedded Redis cache + FastAPI HTTP proxy for Dhan API v2.
  - Async token-bucket `RateGovernor` (1 call/sec per endpoint type).
  - Centralized Supabase credentials sync (`dhan:auth`).
  - Fly.io deployment in Mumbai (`bom`) region (`https://dhan-redis-hub.fly.dev`).
