"""Regression tests for the HP Printer REST data cache."""

from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.hpprinter.common.consts import PRODUCT_STATUS_ENDPOINT
from custom_components.hpprinter.managers.rest_api import RestAPIv2


@pytest.fixture
def api():
    manager = Mock()
    manager.endpoints = ["/counters"]
    manager.entry_id = "test-printer"
    manager.get_update_interval.return_value = 0
    return RestAPIv2(None, manager)


@pytest.mark.asyncio
async def test_failed_counter_poll_keeps_previous_payload(api):
    api._raw_data["/counters"] = {"TotalImpressions": "1945"}
    api._get_request = AsyncMock(return_value=None)

    await api._update_endpoint_data("/counters")

    assert api._raw_data["/counters"] == {"TotalImpressions": "1945"}
    assert api._last_successful_update is None


@pytest.mark.asyncio
async def test_successful_counter_poll_updates_timestamp(api):
    api._get_request = AsyncMock(return_value={"TotalImpressions": "1945"})

    assert await api._update_endpoint_data("/counters")
    assert api._raw_data["/counters"]["TotalImpressions"] == "1945"
    assert api._last_successful_update is not None
    assert api._cache_dirty


@pytest.mark.asyncio
async def test_offline_status_does_not_replace_cached_counters(api):
    api._raw_data["/counters"] = {"TotalImpressions": "1945"}
    api._get_request = AsyncMock(return_value=None)

    await api._update_product_status_endpoint_data()

    assert api.is_online is False
    assert api._raw_data["/counters"] == {"TotalImpressions": "1945"}
    assert api._raw_data[PRODUCT_STATUS_ENDPOINT] is not None
