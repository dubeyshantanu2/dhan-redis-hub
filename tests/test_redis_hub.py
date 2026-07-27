import json
import pytest
import asyncio
from unittest.mock import MagicMock, patch
from governor import RateGovernor
from client import DhanRedisClient

@pytest.mark.asyncio
async def test_rate_governor_throttling():
    governor = RateGovernor()
    start_time = asyncio.get_event_loop().time()
    
    # Trigger 3 slots with 0.1s min interval
    await governor.wait_for_slot("test_endpoint", 0.1)
    await governor.wait_for_slot("test_endpoint", 0.1)
    await governor.wait_for_slot("test_endpoint", 0.1)
    
    elapsed = asyncio.get_event_loop().time() - start_time
    assert elapsed >= 0.18, f"Governor failed to throttle: elapsed time was {elapsed:.3f}s"

def test_client_cache_hit():
    mock_redis = MagicMock()
    fake_option_chain = {"status": "success", "data": {"OC": {}}}
    mock_redis.get.return_value = json.dumps(fake_option_chain)

    with patch("client.Redis", return_value=mock_redis):
        client = DhanRedisClient(redis_host="localhost", redis_port=6379)
        res = client.get_option_chain("NIFTY", "2026-07-30")

    assert res == fake_option_chain
    mock_redis.get.assert_called_once_with("dhan:optionchain:NIFTY:2026-07-30")

def test_client_auth_retrieval():
    mock_redis = MagicMock()
    fake_auth = {"client_id": "12345", "access_token": "token_abc"}
    mock_redis.get.return_value = json.dumps(fake_auth)

    with patch("client.Redis", return_value=mock_redis):
        client = DhanRedisClient(redis_host="localhost", redis_port=6379)
        auth = client.get_auth()

    assert auth == fake_auth
    mock_redis.get.assert_called_once_with("dhan:auth")

@pytest.mark.asyncio
async def test_fetch_and_cache_expiry_list_caching():
    from poller import fetch_and_cache_expiry_list
    from config import settings
    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # Cache miss

    fake_auth = json.dumps({"client_id": "123", "access_token": "abc"})
    mock_redis.get.side_effect = lambda key: fake_auth if key == "dhan:auth" else None

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"status": "success", "data": ["2026-07-30", "2026-08-06"]}

    with patch("httpx.AsyncClient.post", new_callable=pytest.importorskip("unittest.mock").AsyncMock) as mock_post:
        mock_post.return_value = fake_resp
        res = await fetch_and_cache_expiry_list(mock_redis, "NIFTY", 13, "IDX_I")

    assert res == ["2026-07-30", "2026-08-06"]
    mock_redis.set.assert_called_once_with("dhan:expirylist:NIFTY", json.dumps(["2026-07-30", "2026-08-06"]), ex=43200)

    # Test cache HIT
    mock_redis.get.side_effect = None
    mock_redis.get.return_value = json.dumps(["2026-07-30", "2026-08-06"])
    res_hit = await fetch_and_cache_expiry_list(mock_redis, "NIFTY", 13, "IDX_I")
    assert res_hit == ["2026-07-30", "2026-08-06"]
    assert mock_post.await_count == 1

@pytest.mark.asyncio
async def test_fetch_and_cache_expiry_list_raw_list_response():
    from poller import fetch_and_cache_expiry_list
    mock_redis = MagicMock()

    fake_auth = json.dumps({"client_id": "123", "access_token": "abc"})
    mock_redis.get.side_effect = lambda key: fake_auth if key == "dhan:auth" else None

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = ["2026-07-30", "2026-08-06"]

    with patch("httpx.AsyncClient.post", new_callable=pytest.importorskip("unittest.mock").AsyncMock) as mock_post:
        mock_post.return_value = fake_resp
        res = await fetch_and_cache_expiry_list(mock_redis, "BANKNIFTY", 25, "IDX_I")

    assert res == ["2026-07-30", "2026-08-06"]
    mock_redis.set.assert_called_once_with("dhan:expirylist:BANKNIFTY", json.dumps(["2026-07-30", "2026-08-06"]), ex=43200)

@pytest.mark.asyncio
async def test_background_universe_poller_delays():
    from app import background_universe_poller
    from config import settings
    
    sleep_calls = []

    async def mock_sleep(duration):
        sleep_calls.append(duration)
        if len(sleep_calls) >= 5:  # 4 x 1.0s + 1 x 5.0s
            raise asyncio.CancelledError()

    with patch("app.redis_client") as mock_redis, \
         patch("app.fetch_and_cache_expiry_list", new_callable=pytest.importorskip("unittest.mock").AsyncMock) as mock_expiry, \
         patch("app.fetch_and_cache_option_chain", new_callable=pytest.importorskip("unittest.mock").AsyncMock) as mock_oc, \
         patch("asyncio.sleep", side_effect=mock_sleep):
        
        mock_redis.get.return_value = json.dumps({"client_id": "123", "access_token": "abc"})
        mock_expiry.return_value = ["2026-07-30"]

        try:
            await background_universe_poller()
        except asyncio.CancelledError:
            pass

    assert sleep_calls == [2.5, 2.5, 2.5, 2.5, 10.0]
    assert mock_expiry.call_count == 4
    assert mock_oc.call_count == 4

def test_index_scrip_resolution():
    from config import INDEX_SCRIP_MAP
    from client import DhanRedisClient
    
    assert INDEX_SCRIP_MAP["NIFTY"] == 13
    assert INDEX_SCRIP_MAP["BANKNIFTY"] == 25
    assert INDEX_SCRIP_MAP["FINNIFTY"] == 27
    assert INDEX_SCRIP_MAP["SENSEX"] == 1

    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps({"status": "success"})
    
    with patch("client.Redis", return_value=mock_redis):
        client = DhanRedisClient()
        # NIFTY defaults to 13
        client.get_option_chain("NIFTY", "2026-07-30")
        mock_redis.get.assert_called_with("dhan:optionchain:NIFTY:2026-07-30")
        
        # BANKNIFTY auto-resolves ID 25 when underlying_scrip is None
        client.get_expiry_list("BANKNIFTY")
        mock_redis.get.assert_called_with("dhan:expirylist:BANKNIFTY")


