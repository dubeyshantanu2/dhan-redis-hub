# Changelog

All notable changes to `dhan-redis-hub`.

## [1.6.0] - 2026-07-28

### Added
- **Project attribution in error logging** — every log record and Discord error alert now names the project that triggered the failure (ARES, Aeolus, gamma-blaster, Kronos, stock-screener), instead of only naming the failing hub component.
  - New `log_context.py`: `X-Project-Name` request header, a `ContextVar` holding the current caller, a `ProjectLogFilter` injecting `%(project)s`, and `configure_logging()`.
  - Hub log format is now `... [project=<name>] <logger>: <message>`; requests with no header are attributed to `hub-internal`.
  - `app.py` middleware tags each request and alerts on unhandled endpoint errors with the responsible project.
  - `send_error_alert(..., project=...)` prints a `Project` line and includes the project in the dedup key, so the same failure from two projects raises two alerts. When `project` is omitted it falls back to the active request context, so existing call sites (e.g. `RateGovernor.handle_429_backoff`) stay attributed.
  - `normalize_project()` sanitizes the client-supplied header (strips control characters, newlines and backticks, collapses whitespace, truncates to 64 chars) before it reaches log lines or Discord markdown.
  - Alert cooldown is keyed on the `(project, component, message)` tuple, so no delimiter collision can suppress an unrelated alert.
  - `dispatch_error_alert()` fires alerts as retained background tasks — the request path never waits on Discord, and pending alerts cannot be garbage-collected.
  - `DhanRedisClient(project_name=...)` (defaults to `$PROJECT_NAME`) sends the header on every hub proxy call and prefixes its own error logs with the project.

## [1.5.0] - 2026-07-28

### Fixed
- **WebSocket Tick Pipeline Repaired (TASK-006)** — `dhan:ticks:<security_id>` was publishing **zero ticks, permanently**. Three independent defects in the hand-rolled `ws_feed.py`, each alone sufficient:
  - Never sent a v2 subscribe frame after connecting (`_subscribed_instruments` was assigned once and never used), so Dhan sent nothing.
  - Could not decode the binary market-data protocol — non-text frames were reduced to `{"raw": hex}`, making the `security_id`/`LTP` lookup permanently `False` and the Redis write + publish unreachable.
  - Extracted LTP only; no depth, volume, or buy/sell quantities.
  - **Impact:** `client.subscribe_ticks()` blocked forever in every consuming project. AEOLUS opened its own direct Dhan WebSocket to get depth/volume, violating the hub's founding constraint that only `dhan-redis-hub` talks to `api.dhan.co`.

### Changed
- **`ws_feed.py` rewritten on `dhanhq.MarketFeed`** — the vendor SDK owns the binary wire format (subscribe frames, `struct` unpacking, disconnect codes) instead of ~200 lines of hand-rolled parsing. Public surface (`__init__`, `start()`, `stop()`) unchanged, so `app.py` and `client.py` needed no edits.
- Indices subscribe at `Ticker`; futures legs at `Full` — the only v2 mode bundling 5-level depth with LTP, volume, and OI in one packet.
- Reconnect uses exponential backoff (1s → 60s, reset after a sustained connection) and **re-reads credentials from Redis on every attempt**, so daily Dhan token expiry heals automatically.

### Added
- `resolve_futures_security_id()` — resolves the current-month futures contract from the already-cached scrip master, so the monthly roll needs no config edit. Matches `'<SYMBOL> <MON> FUT'` exactly, so NIFTY never resolves to NIFTYNXT50.
- `dhan:tick:<security_id>` — short-lived (60s) last-tick snapshot so a subscriber connecting between ticks has a starting value.
- WS config in `config.py`: `ws_index_instruments`, `ws_futures_symbols` (env `WS_FUTURES_SYMBOLS`), `ttl_tick_snapshot`, and the three `ws_*_backoff_*` settings.
- `expiry` carried through `fetch_and_cache_scrip_master()`'s parsed map (additive; existing keys unchanged). Cache key versioned to `dhan:scrip_master:v2` so a payload written before `expiry` existed cannot be served — otherwise the 24h TTL would have silently dropped the futures leg for a full day after deploy.
- Expiry compared as a full `YYYY-MM-DD HH:MM:SS` instant rather than a date, so the contract roll happens at the actual expiry time instead of the following midnight. Date-only values are treated as end-of-day.
- `dhanhq>=2.0.0,<3.0.0` in `requirements.txt` (tested against 2.2.0).
- `tests/test_ws_feed.py` — 13 tests (25/25 suite passing).

### Fixed — regression guard
- The WS path no longer writes to `dhan:quote:<id>`. That key belongs to `poller.fetch_and_cache_quote()` and carries Dhan **REST** field names (`last_price`, `buy_quantity`, `ohlc.high`, `depth.buy`); WS packets use different names (`LTP`, `total_buy_quantity`, `high`, `depth[].bid_price`). Sharing it would have made `/quote` return two schemas at random.

### Verified
Live, during market hours (NIFTY spot ~23,998), full local stack against real Dhan: **196 ticks in 20s across 5 instruments (~10/s)**, futures `Full` packet carrying all 5 depth levels plus `volume`, `total_buy_quantity`, `total_sell_quantity`, `high`, `low`. `/expirylist`, `/optionchain`, `/quote` regression-checked with unchanged response shapes. See `reports/debug/TASK-006_debug-report.md`.

### Known Issue (not fixed — outside TASK-006 scope)
- `python-dotenv` is declared in `requirements.txt` but `load_dotenv()` is never called anywhere. The README's documented local-run flow (`cp .env.example .env` → `uvicorn app:app`) silently ignores `.env`. Deployed environments are unaffected (Fly secrets / docker-compose inject real env vars).

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
