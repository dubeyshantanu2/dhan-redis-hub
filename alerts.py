import logging
import httpx
from datetime import datetime, timezone, timedelta
from config import settings

logger = logging.getLogger("dhan-redis-hub.alerts")

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

    redis_status = "CONNECTED (localhost:6379)" if redis_connected else "DISCONNECTED"
    auth_status = "ACTIVE (Supabase Sync)" if auth_synced else "FAILED"

    msg = f"""```diff
+ =================================================================
+ 🚀 DHAN REDIS HUB — Initialization Complete
+ =================================================================
+ [+] Status        : ONLINE
+ [+] Fly Region    : bom (Mumbai)
+ [+] Redis Cache   : {redis_status}
+ [+] Dhan Auth     : {auth_status}
+ [+] Rate Governor : ACTIVE (1 req/sec limit)
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

async def send_error_alert(error_msg: str, component: str = "Redis Hub") -> None:
    """
    Sends a system alert regarding errors (e.g. Redis disconnect, Dhan auth fail, 429 rate limit) to Discord.
    """
    webhook_url = settings.discord_health_webhook_url
    if not webhook_url:
        logger.debug("Discord health webhook URL not configured, skipping error alert.")
        return

    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist).strftime("%H:%M:%S")

    msg = f"""```diff
- 🚨 DHAN REDIS HUB — SYSTEM ALERT
- ──────────────────────────────────
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
            logger.info(f"Sent error alert to Discord health channel: {error_msg}")
        except Exception as e:
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

    msg = f"""```diff
- =================================================================
- 🛑 DHAN REDIS HUB — Microservice Shutdown
- =================================================================
- [-] Status    : OFFLINE
- [-] Fly Region: bom (Mumbai)
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

