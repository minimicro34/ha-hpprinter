"""Regression tests for HTTP handling and persistent printer data."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from aiohttp import ClientResponseError

from custom_components.hpprinter.common.consts import PRODUCT_STATUS_ENDPOINT
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
