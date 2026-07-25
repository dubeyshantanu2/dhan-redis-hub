# Changelog

All notable changes to `dhan-redis-hub`.

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
