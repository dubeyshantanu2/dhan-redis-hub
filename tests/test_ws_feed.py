import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dhanhq import MarketFeed

from ws_feed import DhanWebSocketHub, resolve_futures_security_id

# Mirrors the scrip master shape after poller.fetch_and_cache_scrip_master().
# NIFTYNXT50 rows are present on purpose -- they are the prefix collision the
# resolver has to reject.
FAKE_SCRIP_MAP = {
    "NIFTY JUL FUT": {"security_id": "61093", "expiry": "2026-07-28 14:30:00"},
    "NIFTY AUG FUT": {"security_id": "58072", "expiry": "2026-08-25 14:30:00"},
    "NIFTY SEP FUT": {"security_id": "68407", "expiry": "2026-09-29 14:30:00"},
    "NIFTYNXT50 JUL FUT": {"security_id": "61094", "expiry": "2026-07-28 14:30:00"},
    "NIFTYNXT50 AUG FUT": {"security_id": "58073", "expiry": "2026-08-25 14:30:00"},
    "NIFTY 24000 CALL": {"security_id": "63929", "expiry": "2026-07-28 14:30:00"},
}


@pytest.mark.asyncio
async def test_resolve_futures_picks_nearest_unexpired():
    with patch("ws_feed.fetch_and_cache_scrip_master", AsyncMock(return_value=FAKE_SCRIP_MAP)), \
         patch("ws_feed.time.strftime", return_value="2026-07-28 10:36:00"):
        result = await resolve_futures_security_id(MagicMock(), "NIFTY")

    assert result == "61093", "Should pick the JUL contract, expiring today but not yet expired"


@pytest.mark.asyncio
async def test_resolve_futures_rolls_past_expired_contract():
    """After JUL expires, the resolver must roll to AUG with no config edit."""
    with patch("ws_feed.fetch_and_cache_scrip_master", AsyncMock(return_value=FAKE_SCRIP_MAP)), \
         patch("ws_feed.time.strftime", return_value="2026-07-29 09:15:00"):
        result = await resolve_futures_security_id(MagicMock(), "NIFTY")

    assert result == "58072"


@pytest.mark.asyncio
async def test_resolve_futures_rolls_at_intraday_expiry_instant():
    """The roll must happen at the contract's expiry time, not at midnight.

    Between 14:30 and market close on expiry day the JUL contract is dead;
    a date-only comparison would keep subscribing it for another 9 hours.
    """
    with patch("ws_feed.fetch_and_cache_scrip_master", AsyncMock(return_value=FAKE_SCRIP_MAP)), \
         patch("ws_feed.time.strftime", return_value="2026-07-28 14:29:59"):
        before = await resolve_futures_security_id(MagicMock(), "NIFTY")

    with patch("ws_feed.fetch_and_cache_scrip_master", AsyncMock(return_value=FAKE_SCRIP_MAP)), \
         patch("ws_feed.time.strftime", return_value="2026-07-28 14:30:01"):
        after = await resolve_futures_security_id(MagicMock(), "NIFTY")

    assert before == "61093", "still live one second before expiry"
    assert after == "58072", "must roll to AUG one second after expiry"


@pytest.mark.asyncio
async def test_resolve_futures_skips_legacy_cache_rows_without_expiry():
    """A scrip-master payload cached before 'expiry' existed must not resolve.

    The versioned cache key in poller.py should prevent this reaching us, but a
    stale row must degrade to 'no futures leg' rather than silently picking an
    arbitrary contract.
    """
    legacy = {"NIFTY JUL FUT": {"security_id": "61093"}}
    with patch("ws_feed.fetch_and_cache_scrip_master", AsyncMock(return_value=legacy)), \
         patch("ws_feed.time.strftime", return_value="2026-07-28 10:36:00"):
        result = await resolve_futures_security_id(MagicMock(), "NIFTY")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_futures_accepts_date_only_expiry_through_end_of_day():
    """Date-only expiry values must stay eligible until midnight, not die at 00:00."""
    date_only = {"NIFTY JUL FUT": {"security_id": "61093", "expiry": "2026-07-28"}}
    with patch("ws_feed.fetch_and_cache_scrip_master", AsyncMock(return_value=date_only)), \
         patch("ws_feed.time.strftime", return_value="2026-07-28 15:30:00"):
        result = await resolve_futures_security_id(MagicMock(), "NIFTY")

    assert result == "61093"


@pytest.mark.asyncio
async def test_resolve_futures_ignores_prefix_collision_and_options():
    """'NIFTY' must never resolve to a NIFTYNXT50 contract or an option row."""
    nxt50_ids = {"61094", "58073"}
    with patch("ws_feed.fetch_and_cache_scrip_master", AsyncMock(return_value=FAKE_SCRIP_MAP)), \
         patch("ws_feed.time.strftime", return_value="2026-07-28 10:36:00"):
        result = await resolve_futures_security_id(MagicMock(), "NIFTY")

    assert result not in nxt50_ids
    assert result != "63929"


@pytest.mark.asyncio
async def test_resolve_futures_returns_none_without_scrip_master():
    with patch("ws_feed.fetch_and_cache_scrip_master", AsyncMock(return_value=None)):
        result = await resolve_futures_security_id(MagicMock(), "NIFTY")

    assert result is None, "Unresolvable futures leg must degrade, not raise"


def test_publish_writes_tick_key_and_channel():
    mock_redis = MagicMock()
    hub = DhanWebSocketHub(mock_redis)
    packet = {
        "type": "Full Data",
        "security_id": 61093,
        "LTP": "23987.00",
        "volume": 828685,
        "total_buy_quantity": 74555,
        "total_sell_quantity": 233610,
        "high": "24038.00",
        "low": "23962.30",
        "depth": [{"bid_price": 23985.0, "bid_quantity": 195, "ask_price": 23987.0, "ask_quantity": 1690}],
    }

    hub._publish(packet)

    mock_redis.set.assert_called_once()
    key, payload = mock_redis.set.call_args[0]
    assert key == "dhan:tick:61093"
    mock_redis.publish.assert_called_once_with("dhan:ticks:61093", payload)

    # The whole point of TASK-006's key split: the REST poller owns dhan:quote:*
    # and its Dhan-REST field names. The WS path must never write there.
    assert "dhan:quote:" not in key

    republished = json.loads(payload)
    for field in ("LTP", "volume", "total_buy_quantity", "total_sell_quantity", "high", "low", "depth"):
        assert field in republished, f"{field} must survive to subscribers"


def test_publish_skips_control_frames():
    """Disconnect/control frames carry no security_id and must not hit Redis."""
    mock_redis = MagicMock()
    hub = DhanWebSocketHub(mock_redis)

    hub._publish({"type": "Server Disconnection", "code": 805})
    hub._publish(None)
    hub._publish("not-a-dict")

    mock_redis.set.assert_not_called()
    mock_redis.publish.assert_not_called()


@pytest.mark.asyncio
async def test_build_instruments_modes():
    mock_redis = MagicMock()
    hub = DhanWebSocketHub(mock_redis)

    with patch("ws_feed.resolve_futures_security_id", AsyncMock(return_value="61093")):
        instruments = await hub._build_instruments()

    indices = [i for i in instruments if i[0] == MarketFeed.IDX]
    futures = [i for i in instruments if i[0] == MarketFeed.NSE_FNO]

    assert all(mode == MarketFeed.Ticker for _, _, mode in indices)
    assert ("13" in [sid for _, sid, _ in indices]), "NIFTY spot must be subscribed"
    assert ("21" in [sid for _, sid, _ in indices]), "India VIX must be subscribed"
    # Full is the only v2 mode carrying 5-level depth alongside volume.
    assert futures == [(MarketFeed.NSE_FNO, "61093", MarketFeed.Full)]


@pytest.mark.asyncio
async def test_reconnect_backs_off_and_rereads_credentials():
    """A dropped connection must back off, and must re-read the token from Redis.

    Dhan access tokens expire daily; a token cached on the instance would keep
    a dead connection retrying forever.
    """
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps({"client_id": "c1", "access_token": "t1"})
    hub = DhanWebSocketHub(mock_redis)

    attempts = 0

    def failing_feed(*_args, **_kwargs):
        nonlocal attempts
        feed = MagicMock()

        async def connect():
            nonlocal attempts
            attempts += 1
            if attempts >= 3:
                hub.stop()
            raise ConnectionError("socket dropped")

        feed.connect = connect
        feed.disconnect = AsyncMock()
        return feed

    sleeps = []

    async def fake_sleep(secs):
        sleeps.append(secs)

    with patch("ws_feed.MarketFeed", side_effect=failing_feed), \
         patch("ws_feed.resolve_futures_security_id", AsyncMock(return_value="61093")), \
         patch("ws_feed.asyncio.sleep", fake_sleep):
        await hub.start()

    assert attempts == 3
    assert sleeps == [1.0, 2.0], f"expected exponential backoff, got {sleeps}"
    # One credential read per connection attempt -- never cached across retries.
    assert mock_redis.get.call_count >= attempts


@pytest.mark.asyncio
async def test_build_instruments_degrades_without_futures():
    """An unresolvable futures leg must not take the index legs down with it."""
    hub = DhanWebSocketHub(MagicMock())

    with patch("ws_feed.resolve_futures_security_id", AsyncMock(return_value=None)):
        instruments = await hub._build_instruments()

    assert len(instruments) == 4
    assert all(seg == MarketFeed.IDX for seg, _, _ in instruments)


@pytest.mark.asyncio
async def test_scrip_master_cache_key_is_versioned():
    """A legacy 'dhan:scrip_master' payload must not be served to the resolver.

    The pre-TASK-006 cache has no 'expiry' field and lives for 24h. Reading it
    would drop the futures leg for a whole day after deploy, silently. The
    versioned key sidesteps it entirely.
    """
    from poller import fetch_and_cache_scrip_master

    mock_redis = MagicMock()
    # Legacy key is populated; versioned key is not.
    mock_redis.get.side_effect = lambda key: (
        json.dumps({"NIFTY JUL FUT": {"security_id": "61093"}})
        if key == "dhan:scrip_master" else None
    )

    with patch("poller.httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=RuntimeError("network disabled in test")
        )
        result = await fetch_and_cache_scrip_master(mock_redis)

    # Legacy payload must not be returned; a re-download is attempted instead.
    assert result is None
    assert mock_redis.get.call_args[0][0] == "dhan:scrip_master:v2"
