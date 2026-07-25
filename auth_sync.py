import json
import logging
from redis import Redis
from supabase import create_client, Client
from config import settings

logger = logging.getLogger("dhan-redis-hub.auth_sync")

def sync_dhan_credentials(redis_client: Redis) -> dict | None:
    """
    Fetches active Dhan credentials from Supabase 'api_keys' table (provider='DHAN')
    and stores them in Redis under the key 'dhan:auth'.
    """
    if not settings.supabase_url or not settings.supabase_key:
        logger.warning("Supabase URL or Key not set. Checking existing Redis 'dhan:auth' key...")
        cached_auth = redis_client.get("dhan:auth")
        if cached_auth:
            return json.loads(cached_auth)
        logger.error("No Supabase credentials configured and no cached Dhan auth in Redis.")
        return None

    try:
        supabase: Client = create_client(settings.supabase_url, settings.supabase_key)
        response = supabase.table("api_keys").select("*").eq("provider", "DHAN").execute()
        
        if not response.data or len(response.data) == 0:
            logger.error("No DHAN row found in Supabase 'api_keys' table.")
            cached_auth = redis_client.get("dhan:auth")
            return json.loads(cached_auth) if cached_auth else None

        row = response.data[0]
        client_id = row.get("client_id")
        access_token = row.get("access_token")

        if not client_id or not access_token:
            logger.error("Dhan credentials in Supabase row are incomplete.")
            cached_auth = redis_client.get("dhan:auth")
            return json.loads(cached_auth) if cached_auth else None

        creds = {
            "client_id": str(client_id),
            "access_token": str(access_token),
            "updated_at": row.get("updated_at")
        }

        redis_client.set("dhan:auth", json.dumps(creds), ex=43200)  # 12 hour TTL
        logger.info(f"Successfully synced Dhan credentials for client ID: {client_id} into Redis.")
        return creds

    except Exception as e:
        logger.error(f"Error fetching Dhan credentials from Supabase: {e}")
        cached_auth = redis_client.get("dhan:auth")
        return json.loads(cached_auth) if cached_auth else None
