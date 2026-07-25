import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from redis import Redis

from config import settings
from auth_sync import sync_dhan_credentials
from poller import (
    fetch_and_cache_option_chain,
    fetch_and_cache_expiry_list,
    fetch_and_cache_quote,
    fetch_and_cache_candles,
    fetch_and_cache_scrip_master,
)
from ws_feed import DhanWebSocketHub

from alerts import send_startup_alert, send_error_alert, send_shutdown_alert

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("dhan-redis-hub.app")

redis_client = Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    password=settings.redis_password,
    db=settings.redis_db,
    decode_responses=True
)

ws_hub = DhanWebSocketHub(redis_client)

async def background_universe_poller():
    """Background task polling the default index universe at safe intervals during market hours."""
    logger.info("Starting background universe option chain poller loop...")
    while True:
        try:
            auth_str = redis_client.get("dhan:auth")
            if not auth_str:
                sync_dhan_credentials(redis_client)

            for index_info in settings.default_indices:
                symbol = index_info["symbol"]
                underlying_id = index_info["underlying_id"]
                segment = index_info["segment"]

                expiries = await fetch_and_cache_expiry_list(redis_client, symbol, underlying_id, segment)
                if expiries and len(expiries) > 0:
                    nearest_expiry = expiries[0]
                    await fetch_and_cache_option_chain(
                        redis_client, symbol, underlying_id, segment, nearest_expiry
                    )

            await asyncio.sleep(2.0)  # Polling loop interval
        except asyncio.CancelledError:
            logger.info("Background universe poller cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in background universe poller: {e}")
            asyncio.create_task(send_error_alert(f"Background universe poller error: {e}", component="Poller Loop"))
            await asyncio.sleep(5.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing dhan-redis-hub microservice...")
    auth_data = sync_dhan_credentials(redis_client)
    redis_ok = True
    try:
        redis_ok = bool(redis_client.ping())
    except Exception as e:
        redis_ok = False
        logger.error(f"Redis Ping Failed: {e}")
        asyncio.create_task(send_error_alert(f"Redis connection failed: {e}", component="Redis Cache"))

    asyncio.create_task(send_startup_alert(redis_connected=redis_ok, auth_synced=bool(auth_data)))

    # Start background tasks
    poller_task = asyncio.create_task(background_universe_poller())
    ws_task = asyncio.create_task(ws_hub.start())
    
    yield
    
    # Shutdown
    logger.info("Shutting down dhan-redis-hub...")
    await send_shutdown_alert()
    ws_hub.stop()
    poller_task.cancel()
    ws_task.cancel()

app = FastAPI(
    title="Dhan Redis Hub",
    description="Centralized Redis Caching and Rate Governance Proxy for Dhan API",
    version="1.0.0",
    lifespan=lifespan
)

class OptionChainReq(BaseModel):
    symbol: str
    underlying_scrip: int
    underlying_seg: str
    expiry: str

class ExpiryListReq(BaseModel):
    symbol: str
    underlying_scrip: int
    underlying_seg: str

class QuoteReq(BaseModel):
    security_id: str
    exchange_segment: str = "NSE_EQ"

class CandlesReq(BaseModel):
    security_id: str
    exchange_segment: str
    instrument_type: str
    interval: str
    from_date: str
    to_date: str

@app.get("/")
def health_check():
    auth = redis_client.get("dhan:auth")
    redis_alive = False
    try:
        redis_alive = redis_client.ping()
    except Exception:
        pass

    return {
        "status": "online",
        "redis_connected": redis_alive,
        "auth_synced": auth is not None
    }

@app.post("/sync-auth")
def trigger_auth_sync():
    creds = sync_dhan_credentials(redis_client)
    if not creds:
        raise HTTPException(status_code=500, detail="Failed to sync Dhan authentication credentials.")
    return {"status": "success", "client_id": creds.get("client_id")}

@app.post("/scrip-master")
async def get_scrip_master():
    data = await fetch_and_cache_scrip_master(redis_client)
    if data is None:
        raise HTTPException(status_code=502, detail="Failed to download Scrip Master CSV.")
    return data

@app.post("/optionchain")
async def get_optionchain(req: OptionChainReq):
    data = await fetch_and_cache_option_chain(
        redis_client, req.symbol, req.underlying_scrip, req.underlying_seg, req.expiry
    )
    if data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch option chain from Dhan API.")
    return data

@app.post("/expirylist")
async def get_expirylist(req: ExpiryListReq):
    data = await fetch_and_cache_expiry_list(
        redis_client, req.symbol, req.underlying_scrip, req.underlying_seg
    )
    if data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch expiry list from Dhan API.")
    return data

@app.post("/quote")
async def get_quote(req: QuoteReq):
    data = await fetch_and_cache_quote(redis_client, req.security_id, req.exchange_segment)
    if data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch quote from Dhan API.")
    return data

@app.post("/candles")
async def get_candles(req: CandlesReq):
    data = await fetch_and_cache_candles(
        redis_client,
        req.security_id,
        req.exchange_segment,
        req.instrument_type,
        req.interval,
        req.from_date,
        req.to_date
    )
    if data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch candles from Dhan API.")
    return data
