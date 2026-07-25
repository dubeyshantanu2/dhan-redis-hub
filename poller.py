import json
import logging
import csv
import httpx
from redis import Redis
from config import settings
from governor import rate_governor
from auth_sync import sync_dhan_credentials

logger = logging.getLogger("dhan-redis-hub.poller")

async def get_valid_auth(redis_client: Redis) -> dict:
    """Helper to retrieve valid authentication details from Redis, resyncing if missing."""
    auth_str = redis_client.get("dhan:auth")
    if not auth_str:
        auth_data = sync_dhan_credentials(redis_client)
        if not auth_data:
            raise ValueError("Unable to retrieve Dhan authentication credentials.")
        return auth_data
    return json.loads(auth_str)

async def fetch_and_cache_scrip_master(redis_client: Redis) -> dict | None:
    """
    Downloads Dhan Compact Scrip Master CSV (https://images.dhan.co/api-data/api-scrip-master.csv),
    parses security ID mappings, and caches under 'dhan:scrip_master' for 24 hours.
    """
    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    cache_key = "dhan:scrip_master"

    cached = redis_client.get(cache_key)
    if cached:
        logger.debug(f"Cache HIT for scrip master '{cache_key}'")
        return json.loads(cached)

    logger.info("Downloading Dhan Scrip Master CSV...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()

            scrip_map = {}
            reader = csv.DictReader(resp.text.splitlines())
            for row in reader:
                symbol = row.get("SEM_CUSTOM_SYMBOL") or row.get("SEM_TRADING_SYMBOL")
                security_id = row.get("SEM_SMST_SECURITY_ID")
                if symbol and security_id:
                    scrip_map[symbol.upper()] = {
                        "security_id": security_id,
                        "exchange": row.get("SEM_EXM_EXCH_ID"),
                        "segment": row.get("SEM_SEGMENT"),
                        "lot_size": row.get("SEM_LOT_UNITS")
                    }

            if scrip_map:
                redis_client.set(cache_key, json.dumps(scrip_map), ex=settings.ttl_scrip_master)
                logger.info(f"Cached {len(scrip_map)} instruments in Redis under '{cache_key}'")
                return scrip_map

        except Exception as e:
            logger.error(f"Failed to download/parse Scrip Master CSV: {e}")

    return None

async def fetch_and_cache_option_chain(
    redis_client: Redis,
    symbol: str,
    underlying_scrip: int,
    underlying_seg: str,
    expiry: str
) -> dict | None:
    """
    Fetches the option chain for a given underlying & expiry, governed by RateGovernor,
    and caches the result in Redis under key 'dhan:optionchain:{symbol}:{expiry}'.
    """
    cache_key = f"dhan:optionchain:{symbol.upper()}:{expiry}"
    cached = redis_client.get(cache_key)
    if cached:
        logger.debug(f"Cache HIT for option chain '{cache_key}'")
        return json.loads(cached)

    auth = await get_valid_auth(redis_client)
    headers = {
        "access-token": auth["access_token"],
        "client-id": auth["client_id"],
        "Content-Type": "application/json"
    }
    payload = {
        "UnderlyingScrip": underlying_scrip,
        "UnderlyingSeg": underlying_seg,
        "Expiry": expiry
    }

    url = f"{settings.dhan_api_base}/optionchain"

    await rate_governor.wait_for_slot("optionchain", settings.rate_limit_option_chain_secs)

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(1, 4):
            try:
                resp = await client.post(url, headers=headers, json=payload)
                
                if resp.status_code == 429:
                    await rate_governor.handle_429_backoff(attempt)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if isinstance(data, dict) and ("oc" in data or "data" in data or "last_price" in data or data.get("status") == "success"):
                    redis_client.set(cache_key, json.dumps(data), ex=settings.ttl_option_chain_market)
                    logger.info(f"Cached option chain for {symbol} ({expiry}) in Redis under '{cache_key}'")
                    return data
                else:
                    logger.warning(f"Option chain fetch returned non-success structure: {data}")
                    return None

            except httpx.HTTPStatusError as err:
                logger.error(f"HTTP error fetching option chain for {symbol}: {err}")
            except Exception as err:
                logger.error(f"Error fetching option chain for {symbol}: {err}")

    return None

async def fetch_and_cache_expiry_list(
    redis_client: Redis,
    symbol: str,
    underlying_scrip: int,
    underlying_seg: str
) -> list[str] | None:
    """
    Fetches available expiry dates for an underlying and caches in Redis under 'dhan:expirylist:{symbol}'.
    """
    cache_key = f"dhan:expirylist:{symbol.upper()}"
    cached = redis_client.get(cache_key)
    if cached:
        logger.debug(f"Cache HIT for expiry list '{cache_key}'")
        return json.loads(cached)

    auth = await get_valid_auth(redis_client)
    headers = {
        "access-token": auth["access_token"],
        "client-id": auth["client_id"],
        "Content-Type": "application/json"
    }
    payload = {
        "UnderlyingScrip": underlying_scrip,
        "UnderlyingSeg": underlying_seg
    }

    url = f"{settings.dhan_api_base}/optionchain/expirylist"

    await rate_governor.wait_for_slot("expirylist", 1.0)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            
            expiries = data.get("data", []) if isinstance(data, dict) else []
            if expiries:
                redis_client.set(cache_key, json.dumps(expiries), ex=settings.ttl_expiry_list)
                logger.info(f"Cached expiry list for {symbol} ({len(expiries)} expiries) under '{cache_key}'")
                return expiries

        except Exception as e:
            logger.error(f"Failed to fetch expiry list for {symbol}: {e}")

    return None

async def fetch_and_cache_quote(
    redis_client: Redis,
    security_id: int | str,
    exchange_segment: str = "NSE_EQ"
) -> dict | None:
    """
    Fetches market quote / LTP for a security and caches under 'dhan:quote:{security_id}'.
    """
    cache_key = f"dhan:quote:{security_id}"
    cached = redis_client.get(cache_key)
    if cached:
        logger.debug(f"Cache HIT for quote '{cache_key}'")
        return json.loads(cached)

    auth = await get_valid_auth(redis_client)
    headers = {
        "access-token": auth["access_token"],
        "client-id": auth["client_id"],
        "Content-Type": "application/json"
    }
    payload = {
        exchange_segment: [int(security_id)]
    }

    url = f"{settings.dhan_api_base}/marketfeed/quote"

    await rate_governor.wait_for_slot("quote", settings.rate_limit_quote_secs)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

            quote_data = data.get("data", {}).get(str(security_id), {})
            if quote_data is not None:
                redis_client.set(cache_key, json.dumps(quote_data), ex=settings.ttl_quote)
                logger.info(f"Cached quote for security ID {security_id} under '{cache_key}'")
                return quote_data

        except Exception as e:
            logger.error(f"Error fetching quote for {security_id}: {e}")

    return None

async def fetch_and_cache_candles(
    redis_client: Redis,
    security_id: str,
    exchange_segment: str,
    instrument_type: str,
    interval: str,
    from_date: str,
    to_date: str
) -> dict | None:
    """
    Fetches historical OHLCV candles and caches under 'dhan:candles:{security_id}:{interval}:{from_date}:{to_date}'.
    """
    is_intraday = interval in ["1", "5", "15", "30", "60"]
    cache_key = f"dhan:candles:{security_id}:{interval}:{from_date}:{to_date}"
    cached = redis_client.get(cache_key)
    if cached:
        logger.debug(f"Cache HIT for candles '{cache_key}'")
        return json.loads(cached)

    auth = await get_valid_auth(redis_client)
    headers = {
        "access-token": auth["access_token"],
        "client-id": auth["client_id"],
        "Content-Type": "application/json"
    }
    payload = {
        "securityId": str(security_id),
        "exchangeSegment": exchange_segment,
        "instrument": instrument_type,
        "expiryCode": 0,
        "fromDate": from_date,
        "toDate": to_date
    }

    endpoint = "charts/intraday" if is_intraday else "charts/historical"
    if is_intraday:
        payload["interval"] = interval

    url = f"{settings.dhan_api_base}/{endpoint}"
    ttl = settings.ttl_candles_intraday if is_intraday else settings.ttl_candles_daily

    await rate_governor.wait_for_slot("candles", settings.rate_limit_candles_secs)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if data:
                redis_client.set(cache_key, json.dumps(data), ex=ttl)
                logger.info(f"Cached historical candles for {security_id} under '{cache_key}'")
                return data

        except Exception as e:
            logger.error(f"Error fetching historical candles for {security_id}: {e}")

    return None
