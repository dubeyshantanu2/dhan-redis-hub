import json
import logging
import httpx
from redis import Redis

from config import INDEX_SCRIP_MAP

logger = logging.getLogger("dhan_redis_client")

class DhanRedisClient:
    """
    Client adapter library for trading projects (ARES, Aeolus, gamma-blaster, Kronos, stock-screener).
    Connects directly to the central Redis instance to fetch cached Dhan API data with sub-millisecond latency.
    Falls back to the central hub's REST proxy on cache misses.
    """
    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_password: str | None = None,
        redis_db: int = 0,
        hub_url: str = "http://localhost:8000"
    ):
        self.redis = Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            db=redis_db,
            decode_responses=True
        )
        self.hub_url = hub_url.rstrip("/")

    def get_auth(self) -> dict | None:
        """Retrieves active Dhan credentials stored in Redis."""
        cached = self.redis.get("dhan:auth")
        return json.loads(cached) if cached else None

    def get_scrip_master(self) -> dict | None:
        """Retrieves parsed Scrip Master instrument lookup table from Redis."""
        cache_key = "dhan:scrip_master"
        cached = self.redis.get(cache_key)

        if cached:
            logger.debug(f"Cache HIT for scrip master '{cache_key}'")
            return json.loads(cached)

        logger.info("Cache MISS for scrip master. Requesting from hub proxy...")
        try:
            resp = httpx.post(f"{self.hub_url}/scrip-master", timeout=30.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as err:
            logger.error(f"Failed to fetch scrip master from hub proxy: {err}")
            return None

    def get_option_chain(
        self,
        symbol: str,
        expiry: str,
        underlying_scrip: int | None = None,
        underlying_seg: str = "IDX_I"
    ) -> dict | None:
        """
        Retrieves option chain from Redis. On cache miss, requests the central hub to fetch and cache it.
        """
        if underlying_scrip is None:
            underlying_scrip = INDEX_SCRIP_MAP.get(symbol.upper(), 13)

        cache_key = f"dhan:optionchain:{symbol.upper()}:{expiry}"
        cached = self.redis.get(cache_key)

        if cached:
            logger.debug(f"Cache HIT for option chain '{cache_key}'")
            return json.loads(cached)

        logger.info(f"Cache MISS for option chain '{cache_key}'. Requesting from hub proxy...")
        try:
            resp = httpx.post(
                f"{self.hub_url}/optionchain",
                json={
                    "symbol": symbol,
                    "underlying_scrip": underlying_scrip,
                    "underlying_seg": underlying_seg,
                    "expiry": expiry
                },
                timeout=10.0
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as err:
            logger.error(f"Failed to fetch option chain from hub proxy: {err}")
            return None

    def get_expiry_list(
        self,
        symbol: str,
        underlying_scrip: int | None = None,
        underlying_seg: str = "IDX_I"
    ) -> list[str] | None:
        """
        Retrieves expiry list for an underlying from Redis.
        """
        if underlying_scrip is None:
            underlying_scrip = INDEX_SCRIP_MAP.get(symbol.upper(), 13)

        cache_key = f"dhan:expirylist:{symbol.upper()}"
        cached = self.redis.get(cache_key)

        if cached:
            logger.debug(f"Cache HIT for expiry list '{cache_key}'")
            return json.loads(cached)

        logger.info(f"Cache MISS for expiry list '{cache_key}'. Requesting from hub proxy...")
        try:
            resp = httpx.post(
                f"{self.hub_url}/expirylist",
                json={
                    "symbol": symbol,
                    "underlying_scrip": underlying_scrip,
                    "underlying_seg": underlying_seg
                },
                timeout=10.0
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as err:
            logger.error(f"Failed to fetch expiry list from hub proxy: {err}")
            return None

    def get_quote(self, security_id: int | str, exchange_segment: str = "NSE_EQ") -> dict | None:
        """
        Retrieves latest market quote / LTP for a security from Redis.
        """
        cache_key = f"dhan:quote:{security_id}"
        cached = self.redis.get(cache_key)

        if cached:
            logger.debug(f"Cache HIT for quote '{cache_key}'")
            return json.loads(cached)

        logger.info(f"Cache MISS for quote '{cache_key}'. Requesting from hub proxy...")
        try:
            resp = httpx.post(
                f"{self.hub_url}/quote",
                json={"security_id": str(security_id), "exchange_segment": exchange_segment},
                timeout=10.0
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as err:
            logger.error(f"Failed to fetch quote from hub proxy: {err}")
            return None

    def get_candles(
        self,
        security_id: str,
        exchange_segment: str,
        instrument_type: str,
        interval: str,
        from_date: str,
        to_date: str
    ) -> dict | None:
        """
        Retrieves historical OHLCV candles from Redis.
        """
        cache_key = f"dhan:candles:{security_id}:{interval}:{from_date}:{to_date}"
        cached = self.redis.get(cache_key)

        if cached:
            logger.debug(f"Cache HIT for candles '{cache_key}'")
            return json.loads(cached)

        logger.info(f"Cache MISS for candles '{cache_key}'. Requesting from hub proxy...")
        try:
            resp = httpx.post(
                f"{self.hub_url}/candles",
                json={
                    "security_id": str(security_id),
                    "exchange_segment": exchange_segment,
                    "instrument_type": instrument_type,
                    "interval": interval,
                    "from_date": from_date,
                    "to_date": to_date
                },
                timeout=15.0
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as err:
            logger.error(f"Failed to fetch candles from hub proxy: {err}")
            return None

    def subscribe_ticks(self, security_id: int | str, callback):
        """
        Subscribes to live price ticks over Redis Pub/Sub channel for the given security ID.
        Executes callback(data_dict) on every tick.
        """
        pubsub = self.redis.pubsub()
        channel = f"dhan:ticks:{security_id}"
        pubsub.subscribe(channel)
        logger.info(f"Subscribed to Redis Pub/Sub channel '{channel}'")

        for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    payload = json.loads(message["data"])
                    callback(payload)
                except Exception as err:
                    logger.error(f"Error executing tick callback: {err}")
