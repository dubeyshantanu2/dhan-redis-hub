import asyncio
import os
import time
import logging
import httpx
from datetime import datetime, timezone, timedelta
from config import settings
from log_context import get_project, normalize_project

logger = logging.getLogger("dhan-redis-hub.alerts")

# Keyed by (project, component, error message). A tuple rather than a joined
# string so no delimiter collision can make two distinct errors share a cooldown.
_last_error_times: dict[tuple[str, str, str], float] = {}
ERROR_COOLDOWN_SECS: float = 60.0

# Strong references to in-flight alert tasks. Without this the event loop may
# garbage-collect a pending task and silently drop the alert.
_pending_alert_tasks: set[asyncio.Task] = set()


def dispatch_error_alert(error_msg: str, component: str = "Redis Hub", project: str | None = None) -> None:
    """
    Fires an error alert in the background without blocking the caller.

    Callers on the request path must not wait on Discord's availability, and the
    project is captured here (while still in the caller's context) so the
    detached task attributes the error correctly.
    """
    task = asyncio.create_task(
        send_error_alert(error_msg, component=component, project=project or get_project())
    )
    _pending_alert_tasks.add(task)
    task.add_done_callback(_pending_alert_tasks.discard)

async def send_startup_alert(redis_connected: bool = True, auth_synced: bool = True) -> None:
    """
    Sends an initialization / startup status message to the Discord system-health webhook.
    """
    webhook_url = settings.discord_health_webhook_url
    if not webhook_url:
        logger.debug("Discord health webhook URL not configured, skipping startup alert.")
        return

    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist).strftime("%d-%b-%Y %H:%M:%S")

    fly_region = os.getenv("FLY_REGION", "local")
    redis_status = f"CONNECTED ({settings.redis_host}:{settings.redis_port})" if redis_connected else "DISCONNECTED"
    auth_status = "ACTIVE (Supabase Sync)" if auth_synced else "FAILED"
    gov_status = f"ACTIVE ({settings.rate_limit_option_chain_secs}s interval)"
    overall_status = "ONLINE" if (redis_connected and auth_synced) else "DEGRADED"

    msg = f"""```diff
+ =================================================================
+ 🚀 DHAN REDIS HUB — Initialization Complete
+ =================================================================
+ [+] Status        : {overall_status}
+ [+] Fly Region    : {fly_region}
+ [+] Redis Cache   : {redis_status}
+ [+] Dhan Auth     : {auth_status}
+ [+] Rate Governor : {gov_status}
+ [+] Time          : {now_ist} IST
+ =================================================================
```"""

    payload = {"content": msg}

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("Sent startup alert to Discord health channel.")
        except Exception as e:
            logger.error(f"Failed to send Discord startup alert: {e}")

async def send_error_alert(
    error_msg: str,
    component: str = "Redis Hub",
    cooldown_secs: float = ERROR_COOLDOWN_SECS,
    project: str | None = None,
) -> None:
    """
    Sends a system alert regarding errors to Discord with built-in per-error cooldown coalescing and state pruning.

    `project` names the caller responsible for the error (e.g. "Kronos"), so the
    alert says which project triggered it rather than just which component failed.
    When omitted it defaults to the project of the request context in scope, so
    call sites that never pass it stay correctly attributed.
    """
    webhook_url = settings.discord_health_webhook_url
    if not webhook_url:
        logger.debug("Discord health webhook URL not configured, skipping error alert.")
        return

    now_mono = time.monotonic()
    
    # Prune expired cooldown entries to keep memory bounded
    expired_keys = [k for k, t in _last_error_times.items() if (now_mono - t) > cooldown_secs]
    for k in expired_keys:
        _last_error_times.pop(k, None)

    # Error deduplication & cooldown check
    # Explicit arguments are normalized too: this value is interpolated into
    # Discord markdown and log lines, and not every caller is the middleware.
    project_name = normalize_project(project) if project else get_project()
    # Project is part of the dedup key: the same failure from two projects is
    # two distinct signals and both deserve an alert.
    error_key = (project_name, component, error_msg)
    if error_key in _last_error_times and (now_mono - _last_error_times[error_key]) < cooldown_secs:
        logger.debug(f"Skipping duplicate error alert for '{error_key}' (cooldown active).")
        return

    _last_error_times[error_key] = now_mono

    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist).strftime("%H:%M:%S")

    msg = f"""```diff
- 🚨 DHAN REDIS HUB — SYSTEM ALERT
- ──────────────────────────────────
- ❌ Project   : {project_name}
- ❌ Component : {component}
- ❌ Error     : {error_msg}
- 🕒 Time      : {now_ist} IST
- 🛠️ Action    : Check Fly.io logs & microservice status.
- ──────────────────────────────────
```"""

    payload = {"content": msg}

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info(f"Sent error alert to Discord health channel [project={project_name}]: {error_msg}")
        except Exception as e:
            _last_error_times.pop(error_key, None)  # Reset cooldown state on delivery failure
            logger.error(f"Failed to send Discord error alert: {e}")

async def send_shutdown_alert(reason: str = "Service shutdown / Machine restart") -> None:
    """
    Sends a shutdown status message to Discord when the microservice stops entirely.
    """
    webhook_url = settings.discord_health_webhook_url
    if not webhook_url:
        logger.debug("Discord health webhook URL not configured, skipping shutdown alert.")
        return

    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist).strftime("%d-%b-%Y %H:%M:%S")
    fly_region = os.getenv("FLY_REGION", "local")

    msg = f"""```diff
- =================================================================
- 🛑 DHAN REDIS HUB — Microservice Shutdown
- =================================================================
- [-] Status    : OFFLINE
- [-] Fly Region: {fly_region}
- [-] Reason    : {reason}
- [-] Time      : {now_ist} IST
- =================================================================
```"""

    payload = {"content": msg}

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("Sent shutdown alert to Discord health channel.")
        except Exception as e:
            logger.error(f"Failed to send Discord shutdown alert: {e}")
