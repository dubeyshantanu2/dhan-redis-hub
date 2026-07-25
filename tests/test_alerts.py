import pytest
from unittest.mock import patch, AsyncMock
from alerts import send_startup_alert, send_error_alert, send_shutdown_alert

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
async def test_send_error_alert():
    with patch("alerts.settings.discord_health_webhook_url", "https://discord.com/api/webhooks/test"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.raise_for_status = lambda: None
            
            await send_error_alert("Redis disconnect error", component="Redis Cache")
            assert mock_post.called
            payload = mock_post.call_args[1]["json"]
            assert "SYSTEM ALERT" in payload["content"]
            assert "Redis disconnect error" in payload["content"]

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
