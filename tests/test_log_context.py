import logging

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from alerts import send_error_alert, _last_error_times
from log_context import (
    DEFAULT_PROJECT,
    PROJECT_HEADER,
    ProjectLogFilter,
    get_project,
    set_project,
)


@pytest.fixture(autouse=True)
def clean_alert_state():
    _last_error_times.clear()
    set_project(None)
    yield
    _last_error_times.clear()
    set_project(None)


def test_unset_project_falls_back_to_default():
    assert get_project() == DEFAULT_PROJECT


def test_blank_project_falls_back_to_default():
    set_project("   ")
    assert get_project() == DEFAULT_PROJECT


def test_log_filter_injects_current_project():
    set_project("Kronos")
    record = logging.LogRecord("test", logging.ERROR, "f.py", 1, "boom", None, None)

    assert ProjectLogFilter().filter(record) is True
    assert record.project == "Kronos"


@pytest.mark.asyncio
async def test_error_alert_names_the_project():
    with patch("alerts.settings.discord_health_webhook_url", "https://discord.com/api/webhooks/test"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.raise_for_status = lambda: None

            await send_error_alert("timeout talking to Dhan", component="HTTP API", project="ARES")

            content = mock_post.call_args[1]["json"]["content"]
            assert "ARES" in content


@pytest.mark.asyncio
async def test_same_error_from_two_projects_both_alert():
    """Cooldown dedupes per project, so a shared failure is reported for each caller."""
    with patch("alerts.settings.discord_health_webhook_url", "https://discord.com/api/webhooks/test"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.raise_for_status = lambda: None

            await send_error_alert("upstream 502", component="HTTP API", project="ARES")
            await send_error_alert("upstream 502", component="HTTP API", project="Kronos")
            await send_error_alert("upstream 502", component="HTTP API", project="ARES")

            assert mock_post.call_count == 2


def test_request_header_sets_project_for_the_request():
    import app as app_module

    seen: list[str] = []

    @app_module.app.get("/_project_probe")
    def _probe():
        seen.append(get_project())
        return {"ok": True}

    with TestClient(app_module.app) as client:
        client.get("/_project_probe", headers={PROJECT_HEADER: "gamma-blaster"})
        client.get("/_project_probe")

    assert seen == ["gamma-blaster", DEFAULT_PROJECT]


def test_client_sends_project_header_to_hub():
    from client import DhanRedisClient

    with patch("client.Redis") as mock_redis:
        mock_redis.return_value.get.return_value = None
        dhan = DhanRedisClient(project_name="Aeolus")

        with patch("httpx.post") as mock_post:
            mock_post.return_value.raise_for_status = lambda: None
            mock_post.return_value.json = lambda: {}

            dhan.get_quote("13")

            assert mock_post.call_args[1]["headers"][PROJECT_HEADER] == "Aeolus"
