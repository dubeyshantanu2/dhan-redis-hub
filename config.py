import os
from pydantic import BaseModel

class Config(BaseModel):
    # Redis configuration
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_password: str | None = os.getenv("REDIS_PASSWORD", None)
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    
    # Supabase authentication sync
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_KEY", "")
    
    # Discord Health & System Alerts
    discord_health_webhook_url: str | None = os.getenv("DISCORD_HEALTH_WEBHOOK_URL", os.getenv("DISCORD_WEBHOOK_URL", None))
    
    # Dhan API
    dhan_api_base: str = os.getenv("DHAN_API_BASE", "https://api.dhan.co/v2")
    dhan_ws_url: str = os.getenv("DHAN_WS_URL", "wss://api-feed.dhan.co")
    
    # Rate Governor thresholds (min interval in seconds per endpoint type)
    rate_limit_option_chain_secs: float = float(os.getenv("RATE_LIMIT_OPTION_CHAIN_SECS", "1.0"))
    rate_limit_quote_secs: float = float(os.getenv("RATE_LIMIT_QUOTE_SECS", "1.0"))
    rate_limit_candles_secs: float = float(os.getenv("RATE_LIMIT_CANDLES_SECS", "1.0"))
    
    # TTL Configurations (in seconds)
    ttl_option_chain_market: int = int(os.getenv("TTL_OPTION_CHAIN_MARKET", "2"))
    ttl_option_chain_offmarket: int = int(os.getenv("TTL_OPTION_CHAIN_OFFMARKET", "60"))
    ttl_quote: int = int(os.getenv("TTL_QUOTE", "5"))
    ttl_expiry_list: int = int(os.getenv("TTL_EXPIRY_LIST", "43200"))  # 12 hours
    ttl_candles_intraday: int = int(os.getenv("TTL_CANDLES_INTRADAY", "900"))  # 15 mins
    ttl_candles_daily: int = int(os.getenv("TTL_CANDLES_DAILY", "86400"))  # 24 hours
    ttl_scrip_master: int = int(os.getenv("TTL_SCRIP_MASTER", "86400"))  # 24 hours
    
    # Default Polling Universe
    default_indices: list[dict] = [
        {"symbol": "NIFTY", "underlying_id": 13, "segment": "IDX_I"},
        {"symbol": "BANKNIFTY", "underlying_id": 25, "segment": "IDX_I"},
        {"symbol": "FINNIFTY", "underlying_id": 27, "segment": "IDX_I"},
        {"symbol": "SENSEX", "underlying_id": 51, "segment": "BSE_FNO"},
    ]

INDEX_SCRIP_MAP: dict[str, int] = {
    "NIFTY": 13,
    "BANKNIFTY": 25,
    "FINNIFTY": 27,
    "SENSEX": 51,
}

settings = Config()
