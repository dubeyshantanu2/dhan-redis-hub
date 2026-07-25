import asyncio
import json
import logging
import websockets
from redis import Redis
from config import settings
from auth_sync import sync_dhan_credentials

logger = logging.getLogger("dhan-redis-hub.ws_feed")

class DhanWebSocketHub:
    """
    Single-instance Dhan WebSocket hub that maintains one WebSocket feed connection,
    listens for live price ticks/quotes, updates Redis quote keys, and broadcasts
    ticks to Redis Pub/Sub channels ('dhan:ticks:<security_id>').
    """
    def __init__(self, redis_client: Redis):
        self.redis_client = redis_client
        self.running = False
        self._subscribed_instruments = set()

    async def start(self):
        self.running = True
        retry_delay = 2.0

        while self.running:
            auth_str = self.redis_client.get("dhan:auth")
            if not auth_str:
                auth = sync_dhan_credentials(self.redis_client)
            else:
                auth = json.loads(auth_str)

            if not auth or "access_token" not in auth or "client_id" not in auth:
                logger.error("Dhan WebSocket Hub: No active credentials found in Redis/Supabase. Retrying in 10s...")
                await asyncio.sleep(10)
                continue

            ws_url = (
                f"{settings.dhan_ws_url}?"
                f"version=2&token={auth['access_token']}&clientId={auth['client_id']}&authType=2"
            )

            logger.info("Connecting single-instance Dhan WebSocket feed...")

            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("Dhan WebSocket Hub connected successfully!")
                    retry_delay = 2.0

                    while self.running:
                        message = await ws.recv()
                        await self._handle_ws_message(message)

            except Exception as err:
                logger.warning(f"Dhan WebSocket connection lost: {err}. Reconnecting in {retry_delay:.1f}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60.0)

    async def _handle_ws_message(self, message):
        """
        Parses incoming Dhan WebSocket binary/JSON packet and publishes to Redis Pub/Sub.
        """
        try:
            if isinstance(message, str):
                data = json.loads(message)
            else:
                # Handle binary packet parsing if struct formats are received
                # Extract basic payload
                data = {"raw": message.hex()}

            security_id = data.get("security_id") or data.get("securityId")
            ltp = data.get("LTP") or data.get("ltp")

            if security_id and ltp is not None:
                # Update Redis key
                quote_key = f"dhan:quote:{security_id}"
                self.redis_client.set(quote_key, json.dumps(data), ex=5)

                # Broadcast to Pub/Sub channel
                channel = f"dhan:ticks:{security_id}"
                self.redis_client.publish(channel, json.dumps(data))
                logger.debug(f"Broadcast tick for security {security_id}: LTP={ltp}")

        except Exception as err:
            logger.error(f"Error handling Dhan WS message: {err}")

    def stop(self):
        self.running = False
