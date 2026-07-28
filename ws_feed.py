"""Live Dhan v2 WebSocket feed → Redis Pub/Sub (TASK-006).

Drives the vendor `dhanhq.MarketFeed` rather than a hand-rolled websockets
client. The v2 market data protocol is binary (struct-packed Ticker/Quote/Full
frames) and requires an explicit subscribe frame after connect -- both live in
the SDK and are deliberately not reimplemented here.

Indices subscribe at Ticker (they have no depth or volume). Futures legs
subscribe at Full, the only v2 mode that bundles 5-level depth with LTP,
volume, and OI in one packet.
"""

import asyncio
import json
import logging
import re
import time

from dhanhq import DhanContext, MarketFeed
from redis import Redis

from auth_sync import sync_dhan_credentials
from config import settings
from poller import fetch_and_cache_scrip_master

logger = logging.getLogger("dhan-redis-hub.ws_feed")


def _expiry_instant(raw: str) -> str:
    """Normalise SEM_EXPIRY_DATE to a lexicographically comparable instant.

    The CSV gives futures rows a full 'YYYY-MM-DD HH:MM:SS' timestamp, so a
    contract must stop being eligible once that instant passes -- not merely
    once the date rolls over. Date-only values are treated as end-of-day so
    they stay eligible through their expiry date rather than dying at midnight.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    return f"{raw} 23:59:59" if len(raw) == 10 else raw


async def resolve_futures_security_id(redis_client: Redis, symbol: str) -> str | None:
    """Nearest non-expired futures contract ID for `symbol`, from the cached scrip master.

    Matches SEM_CUSTOM_SYMBOL of the form '<SYMBOL> <MON> FUT' exactly, so 'NIFTY'
    resolves to the NIFTY future and never to NIFTYNXT50. Returns None when the
    scrip master is unavailable or no contract matches -- callers subscribe the
    index legs anyway rather than failing the whole feed.
    """
    scrip_map = await fetch_and_cache_scrip_master(redis_client)
    if not scrip_map:
        logger.warning("Scrip master unavailable; cannot resolve %s futures leg.", symbol)
        return None

    pattern = re.compile(rf"^{re.escape(symbol.upper())} [A-Z]{{3}} FUT$")
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    candidates = []
    for name, info in scrip_map.items():
        if not pattern.match(name):
            continue
        # An empty expiry (legacy cache row) sorts below `now` and is skipped,
        # so a stale payload degrades to "no futures leg" rather than picking
        # an arbitrary contract.
        expiry = _expiry_instant(info.get("expiry", ""))
        if expiry >= now:
            candidates.append((expiry, info["security_id"]))
    if not candidates:
        logger.warning("No non-expired futures contract found for %s.", symbol)
        return None

    expiry, security_id = min(candidates)
    logger.info("Resolved %s futures leg: security_id=%s (expiry %s)", symbol, security_id, expiry)
    return str(security_id)


class DhanWebSocketHub:
    """Single-instance Dhan WebSocket hub.

    Maintains one feed connection, publishes every parsed packet to
    'dhan:ticks:<security_id>', and keeps a short-lived snapshot at
    'dhan:tick:<security_id>' so a subscriber that connects between ticks
    still has a value to start from.
    """

    def __init__(self, redis_client: Redis):
        self.redis_client = redis_client
        self.running = False

    async def start(self):
        """Supervisor loop. Returns only once stop() is called.

        Credentials are re-read from Redis on every reconnect rather than held
        on the instance -- Dhan access tokens expire daily, and a stale token
        must not survive into the next connection attempt.
        """
        self.running = True
        backoff = settings.ws_initial_backoff_secs

        while self.running:
            auth = await self._get_auth()
            if not auth:
                logger.error("Dhan WebSocket Hub: no credentials in Redis/Supabase. Retrying in 10s...")
                await asyncio.sleep(10)
                continue

            instruments = await self._build_instruments()
            if not instruments:
                logger.error("Dhan WebSocket Hub: empty instrument universe. Retrying in 10s...")
                await asyncio.sleep(10)
                continue

            context = DhanContext(auth["client_id"], auth["access_token"])
            feed = MarketFeed(context, instruments, version="v2")
            connected_at = None

            try:
                logger.info("Connecting Dhan WebSocket feed (%d instruments)...", len(instruments))
                await feed.connect()
                connected_at = time.monotonic()
                logger.info("Dhan WebSocket Hub connected.")

                while self.running:
                    packet = await feed.get_instrument_data()
                    self._publish(packet)
                    # Only credit a connection as healthy once it has held for a
                    # sustained period, so a connect/drop flap keeps backing off.
                    if time.monotonic() - connected_at >= settings.ws_backoff_reset_after_secs:
                        backoff = settings.ws_initial_backoff_secs

            except asyncio.CancelledError:
                logger.info("Dhan WebSocket Hub cancelled.")
                self.running = False
                raise
            except Exception as err:
                logger.warning("Dhan WebSocket connection lost: %s. Reconnecting in %.1fs...", err, backoff)
            finally:
                try:
                    await feed.disconnect()
                except Exception:
                    pass

            if not self.running:
                break
            await asyncio.sleep(backoff)
            # Clamp against the initial value: a misconfigured max below the
            # initial delay would otherwise pin every retry at the smaller
            # number and hammer Dhan on a sustained outage.
            ceiling = max(settings.ws_max_backoff_secs, settings.ws_initial_backoff_secs)
            backoff = min(backoff * 2, ceiling)

    async def _get_auth(self) -> dict | None:
        auth_str = self.redis_client.get("dhan:auth")
        if auth_str:
            auth = json.loads(auth_str)
        else:
            auth = sync_dhan_credentials(self.redis_client)
        if auth and "access_token" in auth and "client_id" in auth:
            return auth
        return None

    async def _build_instruments(self) -> list[tuple[int, str, int]]:
        """(exchange_segment, security_id, request_code) tuples for MarketFeed."""
        instruments = [
            (MarketFeed.IDX, idx["security_id"], MarketFeed.Ticker)
            for idx in settings.ws_index_instruments
        ]

        for symbol in settings.ws_futures_symbols:
            symbol = symbol.strip()
            if not symbol:
                continue
            security_id = await resolve_futures_security_id(self.redis_client, symbol)
            if security_id:
                instruments.append((MarketFeed.NSE_FNO, security_id, MarketFeed.Full))

        return instruments

    def _publish(self, packet):
        """Publish a parsed packet to Pub/Sub and snapshot it.

        Published verbatim: the SDK's field names (LTP, volume,
        total_buy_quantity, total_sell_quantity, high, low, depth[]) are what
        downstream consumers already parse. Control and disconnect frames carry
        no security_id and are skipped.
        """
        if not isinstance(packet, dict):
            return
        security_id = packet.get("security_id")
        if security_id is None:
            return

        payload = json.dumps(packet)
        self.redis_client.set(f"dhan:tick:{security_id}", payload, ex=settings.ttl_tick_snapshot)
        self.redis_client.publish(f"dhan:ticks:{security_id}", payload)
        logger.debug("Tick published for %s (%s)", security_id, packet.get("type"))

    def stop(self):
        self.running = False
