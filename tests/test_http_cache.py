"""Regression tests for HTTP handling and persistent printer data."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from aiohttp import ClientResponseError

from custom_components.hpprinter.common.consts import PRODUCT_STATUS_ENDPOINT, PRODUCT_STATUS_OFFLINE_PAYLOAD
from custom_components.hpprinter.managers.rest_api import RestAPIv2


@pytest.fixture
def api():
    manager = Mock()
    manager.endpoints = ["/counters"]
    manager.entry_id = "test"
    manager.config_data = SimpleNamespace(url="http://printer", hostname="printer")
    manager.get_update_interval.return_value = 0
    instance = RestAPIv2(None, manager)
    instance._session = MagicMock()
    return instance


def response(api, body="", content_type="text/xml", error=None):
    reply = api._session.get.return_value.__aenter__.return_value
    reply.content_type = content_type
    reply.text = AsyncMock(return_value=body)
    reply.raise_for_status = Mock(side_effect=error)
    return reply


@pytest.mark.asyncio
async def test_json_response_clears_timeout_counter(api):
    response(api, '{"count": 42}', "application/javascript")
    api._secondary_timeout_counts["/counters"] = 2
    assert await api._get_request("/counters") == {"count": 42}
    assert "/counters" not in api._secondary_timeout_counts


@pytest.mark.asyncio
async def test_xml_namespaces_are_removed(api):
    response(api, '<p:Root xmlns:p="urn:test"><p:Count p:unit="pages">42</p:Count></p:Root>')
    assert await api._get_request("/counters") == {
        "Root": {"Count": {"@unit": "pages", "#text": "42"}}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 500])
async def test_secondary_http_failure_returns_no_payload(api, status):
    error = ClientResponseError(Mock(real_url="http://printer"), (), status=status)
    response(api, error=error)
    assert await api._get_request("/counters") is None


@pytest.mark.asyncio
async def test_status_http_failure_records_reason(api):
    error = ClientResponseError(Mock(real_url="http://printer"), (), status=503)
    response(api, error=error)
    assert await api._get_request(PRODUCT_STATUS_ENDPOINT) is None
    assert "503" in api._last_status_failure


@pytest.mark.asyncio
async def test_secondary_timeout_warns_only_on_third_failure(api, caplog):
    response(api, error=TimeoutError())
    for _ in range(4):
        assert await api._get_request("/counters") is None
    assert api._secondary_timeout_counts["/counters"] == 4
    assert sum("3 consecutive times" in r.message for r in caplog.records) == 1


@pytest.mark.asyncio
async def test_status_timeout_records_reason(api):
    response(api, error=TimeoutError())
    assert await api._get_request(PRODUCT_STATUS_ENDPOINT) is None
    assert api._last_status_failure == "request timed out"


@pytest.mark.asyncio
async def test_invalid_xml_does_not_replace_cached_data(api):
    response(api, "<broken>")
    api._raw_data["/counters"] = {"count": 42}
    await api._update_endpoint_data("/counters")
    assert api.raw_data["/counters"] == {"count": 42}


@pytest.mark.asyncio
async def test_cache_restore_does_not_restore_online_status(api):
    api._cache_store = Mock()
    api._cache_store.async_load = AsyncMock(return_value={
        "endpoints": {"/counters": {"count": 42}, PRODUCT_STATUS_ENDPOINT: {"old": True}},
        "last_successful_update": 1234,
    })
    api._update_product_status_endpoint_data = AsyncMock()
    await api.initialize()
    assert api.raw_data == {"/counters": {"count": 42}}
    assert api._last_successful_update == 1234
    assert not api.is_online


@pytest.mark.asyncio
async def test_cache_save_excludes_status_and_failed_payloads(api):
    api._cache_store = Mock()
    api._cache_store.async_save = AsyncMock()
    api._raw_data = {"/counters": {"count": 42}, "/failed": None, PRODUCT_STATUS_ENDPOINT: {}}
    api._cache_dirty = True
    api._last_successful_update = 1234
    api._update_product_status_endpoint_data = AsyncMock(return_value=False)
    api._get_devices_data = Mock(return_value=[])
    await api.update()
    api._cache_store.async_save.assert_awaited_once_with({
        "endpoints": {"/counters": {"count": 42}},
        "last_successful_update": 1234,
    })
    assert not api._cache_dirty


@pytest.mark.asyncio
async def test_terminate_closes_session(api):
    session = api._session
    session.close = AsyncMock()
    await api.terminate()
    session.close.assert_awaited_once()
    assert api._session is None


@pytest.mark.asyncio
async def test_reconnection_refreshes_secondary_endpoints_immediately(api):
    api._is_online = True
    api._raw_data["/counters"] = {"count": 42}
    api._config_manager.get_update_interval.side_effect = (
        lambda endpoint: 0 if endpoint == PRODUCT_STATUS_ENDPOINT else 3600
    )
    api._get_request = AsyncMock(side_effect=[None, {"online": True}, {"count": 43}])
    api._get_devices_data = Mock(return_value=[])
    api._extract_data = Mock()
    from time import time
    api._last_update["/counters"] = time()
    try:
        await api.update()
        assert not api.is_online
        assert api.raw_data[PRODUCT_STATUS_ENDPOINT] == PRODUCT_STATUS_OFFLINE_PAYLOAD
        assert api.raw_data["/counters"] == {"count": 42}
        assert api._get_request.await_count == 1

        # Simulate expiration of the retry delay, without resetting endpoint intervals.
        api._next_status_retry = 0
        await api.update()
        assert api.is_online
        assert api.raw_data["/counters"] == {"count": 43}
        assert [call.args[0] for call in api._get_request.await_args_list] == [
            PRODUCT_STATUS_ENDPOINT, PRODUCT_STATUS_ENDPOINT, "/counters",
        ]
        assert api._status_failure_count == 0
        assert api._failure_warning_handle is None
    finally:
        api._cancel_failure_warning()


@pytest.mark.asyncio
@pytest.mark.parametrize("suspended_endpoint", [PRODUCT_STATUS_ENDPOINT, "/counters"])
async def test_suspend_during_request_discards_response_and_stops_cycle(api, suspended_endpoint):
    api._is_online = True
    api._config_manager.endpoints = ["/counters", "/other"]
    api._raw_data["/counters"] = {"count": 42}
    api._get_devices_data = Mock(return_value=[])
    api._extract_data = Mock()

    async def request(endpoint):
        if endpoint == suspended_endpoint:
            api.suspend_polling()
        return {"count": 99}

    api._get_request = AsyncMock(side_effect=request)
    await api.update()
    assert not api.is_online
    assert api._polling_suspended
    assert api.raw_data[PRODUCT_STATUS_ENDPOINT] == PRODUCT_STATUS_OFFLINE_PAYLOAD
    assert api.raw_data["/counters"] == {"count": 42}
    expected = [PRODUCT_STATUS_ENDPOINT]
    if suspended_endpoint == "/counters":
        expected.append("/counters")
    assert [call.args[0] for call in api._get_request.await_args_list] == expected
    await api.update()
    assert api._get_request.await_count == len(expected)

    api.resume_polling()
    assert not api._polling_suspended
    assert not api._last_update
    api._get_request = AsyncMock(return_value={"count": 43})
    await api.update()
    assert api.is_online
    assert api.raw_data["/counters"] == {"count": 43}
    assert api._get_request.await_count == 3


@pytest.mark.asyncio
async def test_failed_cache_save_is_retried(api, caplog):
    api._cache_store = Mock(async_save=AsyncMock(side_effect=[OSError("disk unavailable"), None]))
    api._raw_data["/counters"] = {"count": 42}
    api._cache_dirty = True
    api._last_successful_update = 1234
    api._update_product_status_endpoint_data = AsyncMock(return_value=False)
    api._get_devices_data = Mock(return_value=[])
    api._extract_data = Mock()
    await api.update()
    assert api._cache_dirty
    assert api.raw_data["/counters"] == {"count": 42}
    assert "disk unavailable" in caplog.text
    await api.update()
    assert not api._cache_dirty
    assert api._last_persisted_success == 1234
    assert api._cache_store.async_save.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("with_hass", [False, True])
async def test_session_creation_recovers_after_initial_failure(api, with_hass, caplog):
    session = api._session
    session.closed = False
    response(api, '{"online": true}', "application/javascript")
    api._session = None
    api._hass = Mock() if with_hass else None
    api._get_devices_data = Mock(return_value=[])
    api._extract_data = Mock()
    factory = "async_create_clientsession" if with_hass else "ClientSession"
    with patch(
        f"custom_components.hpprinter.managers.rest_api.{factory}",
        side_effect=[OSError("session unavailable"), session],
    ) as create:
        await api.initialize()
        assert api._session is None
        assert "session unavailable" in caplog.text
        await api.update(endpoints=[])
        assert api.is_online
        assert api._session is session
        assert create.call_count == 2
        await api.update(endpoints=[])
        assert create.call_count == 2


@pytest.mark.asyncio
async def test_closed_session_is_replaced(api):
    old_session = api._session
    old_session.closed = True
    replacement = MagicMock()
    replacement.closed = False
    api._session = replacement
    response(api, '{"count": 42}', "application/javascript")
    api._session = old_session
    with patch(
        "custom_components.hpprinter.managers.rest_api.ClientSession",
        return_value=replacement,
    ) as create:
        assert await api._get_request("/counters") == {"count": 42}
        assert api._session is replacement
        create.assert_called_once()
        old_session.get.assert_not_called()
