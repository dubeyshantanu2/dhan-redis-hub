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
    # Versioned key: a cache written before 'expiry' was added has no expiry field,
    # and resolve_futures_security_id() would reject every futures row until the
    # 24h TTL lapsed -- silently dropping the futures leg for a whole day after
    # deploy. Bump this suffix whenever the parsed row shape changes.
    cache_key = "dhan:scrip_master:v2"

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
                        "lot_size": row.get("SEM_LOT_UNITS"),
                        # Needed by ws_feed.resolve_futures_security_id() to pick the
                        # nearest non-expired futures contract without a second CSV pass.
                        "expiry": row.get("SEM_EXPIRY_DATE") or ""
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

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(1, 4):
            await rate_governor.wait_for_slot("optionchain", settings.rate_limit_option_chain_secs)
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
            
            expiries = data.get("data") if isinstance(data, dict) else (data if isinstance(data, list) else None)
            if isinstance(expiries, list):
                redis_client.set(cache_key, json.dumps(expiries), ex=settings.ttl_expiry_list)
                logger.info(f"Cached expiry list for {symbol} ({len(expiries)} expiries) under '{cache_key}' with {settings.ttl_expiry_list}s TTL")
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

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(1, 4):
            await rate_governor.wait_for_slot("quote", settings.rate_limit_quote_secs)
            try:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 429:
                    await rate_governor.handle_429_backoff(attempt)
                    continue

                resp.raise_for_status()
                data = resp.json()

                raw_data = data.get("data", {}) if isinstance(data, dict) else {}
                quote_data = (
                    raw_data.get(exchange_segment, {}).get(str(security_id))
                    or raw_data.get(str(security_id))
                )
                if quote_data and isinstance(quote_data, dict):
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

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(1, 4):
            await rate_governor.wait_for_slot("candles", settings.rate_limit_candles_secs)
            try:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 429:
                    await rate_governor.handle_429_backoff(attempt)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if data:
                    redis_client.set(cache_key, json.dumps(data), ex=ttl)
                    logger.info(f"Cached historical candles for {security_id} under '{cache_key}'")
                    return data

            except Exception as e:
                logger.error(f"Error fetching historical candles for {security_id}: {e}")

    return None

async def fetch_and_cache_batch_quotes(
    redis_client: Redis,
    req_payload: dict[str, list[int]]
) -> dict | None:
    """
    Fetches market quotes for a batch of securities, utilizing cache when available,
    and fetching from Dhan API for missing quotes. Caches new results.
    """
    total_ids = sum(len(ids) for ids in req_payload.values())
    if total_ids > settings.batch_quotes_max_total_ids:
        logger.error(f"Batch quotes request exceeds total limit: {total_ids} > {settings.batch_quotes_max_total_ids}")
        return None
        
    for segment, sec_ids in req_payload.items():
        if len(sec_ids) > settings.batch_quotes_max_per_segment_ids:
            logger.error(f"Batch quotes request exceeds segment limit for {segment}: {len(sec_ids)} > {settings.batch_quotes_max_per_segment_ids}")
            return None

    final_results = {}
    missing_payload = {}

    # Check cache first
    for segment, sec_ids in req_payload.items():
        if segment not in final_results:
            final_results[segment] = {}
        for sec_id in sec_ids:
            cache_key = f"dhan:quote:{sec_id}"
            cached = redis_client.get(cache_key)
            if cached:
                logger.debug(f"Cache HIT for quote '{cache_key}'")
                final_results[segment][str(sec_id)] = json.loads(cached)
            else:
                if segment not in missing_payload:
                    missing_payload[segment] = []
                missing_payload[segment].append(int(sec_id))

    if not missing_payload:
        return {"data": final_results}

    auth = await get_valid_auth(redis_client)
    headers = {
        "access-token": auth["access_token"],
        "client-id": auth["client_id"],
        "Content-Type": "application/json"
    }

    url = f"{settings.dhan_api_base}/marketfeed/quote"

    async with httpx.AsyncClient(timeout=30.0) as client:
        success = False
        for attempt in range(1, 4):
            await rate_governor.wait_for_slot("quote", settings.rate_limit_quote_secs)
            try:
                resp = await client.post(url, headers=headers, json=missing_payload)
                if resp.status_code == 429:
                    await rate_governor.handle_429_backoff(attempt)
                    continue

                resp.raise_for_status()
                data = resp.json()

                raw_data = data.get("data", {}) if isinstance(data, dict) else {}
                
                # Cache and merge the missing ones
                for segment, sec_ids in missing_payload.items():
                    seg_data = raw_data.get(segment, {})
                    for sec_id in sec_ids:
                        quote_data = seg_data.get(str(sec_id)) or raw_data.get(str(sec_id))
                        if quote_data and isinstance(quote_data, dict):
                            cache_key = f"dhan:quote:{sec_id}"
                            redis_client.set(cache_key, json.dumps(quote_data), ex=settings.ttl_quote)
                            logger.info(f"Cached quote for security ID {sec_id} under '{cache_key}'")
                            final_results[segment][str(sec_id)] = quote_data

                success = True
                break

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error fetching batch quotes (attempt {attempt}): {e}")
                if e.response.status_code < 500 and e.response.status_code != 429:
                    break
            except Exception as e:
                logger.error(f"Error fetching batch quotes (attempt {attempt}): {e}")

        if not success:
            return None

    return {"data": final_results}
