import pytest
from unittest.mock import patch, AsyncMock
from alerts import send_startup_alert, send_error_alert, send_shutdown_alert, _last_error_times

@pytest.mark.asyncio
async def test_send_startup_alert():
    with patch("alerts.settings.discord_health_webhook_url", "https://discord.com/api/webhooks/test"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.raise_for_status = lambda: None
            
            await send_startup_alert(redis_connected=True, auth_synced=True)
            assert mock_post.called
            payload = mock_post.call_args[1]["json"]
            assert "DHAN REDIS HUB" in payload["content"]
            assert "ONLINE" in payload["content"]

@pytest.mark.asyncio
async def test_send_error_alert_with_cooldown():
    _last_error_times.clear()
    with patch("alerts.settings.discord_health_webhook_url", "https://discord.com/api/webhooks/test"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.raise_for_status = lambda: None
            
            # First call — should post to Discord
            await send_error_alert("Redis disconnect error", component="Redis Cache", cooldown_secs=60.0)
            assert mock_post.call_count == 1
            payload = mock_post.call_args[1]["json"]
            assert "SYSTEM ALERT" in payload["content"]
            assert "Redis disconnect error" in payload["content"]
            
            # Immediate second call with same error — should be suppressed by cooldown
            await send_error_alert("Redis disconnect error", component="Redis Cache", cooldown_secs=60.0)
            assert mock_post.call_count == 1

@pytest.mark.asyncio
async def test_send_shutdown_alert():
    with patch("alerts.settings.discord_health_webhook_url", "https://discord.com/api/webhooks/test"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.raise_for_status = lambda: None
            
            await send_shutdown_alert(reason="Test shutdown")
            assert mock_post.called
            payload = mock_post.call_args[1]["json"]
            assert "DHAN REDIS HUB" in payload["content"]
            assert "OFFLINE" in payload["content"]
