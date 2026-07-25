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
