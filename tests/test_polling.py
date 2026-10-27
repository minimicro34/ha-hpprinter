"""Regression tests for polling suspension and delayed outage logging."""

import asyncio
import logging
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
    manager.config_data.hostname = "test-printer"
    instance = RestAPIv2(None, manager)
    instance._get_devices_data = Mock(return_value=[])
    instance._extract_data = Mock()
    return instance


@pytest.mark.asyncio
async def test_suspend_stops_polling_and_keeps_cached_counters(api):
    api._raw_data["/counters"] = {"TotalImpressions": "1945"}
    api._is_online = True
    api._get_request = AsyncMock()

    api.suspend_polling()
    await api.update()
    await api._update_endpoint_data(PRODUCT_STATUS_ENDPOINT)

    assert not api.is_online
    assert api._raw_data["/counters"]["TotalImpressions"] == "1945"
    assert api._get_request.await_count == 0
    api._extract_data.assert_called_once()


@pytest.mark.asyncio
async def test_warning_is_delayed_and_emitted_once(api, caplog):
    api._get_request = AsyncMock(return_value=None)
    with caplog.at_level(logging.WARNING):
        await api._update_product_status_endpoint_data()
        assert not caplog.records
        api._warn_if_still_offline()
        assert len(caplog.records) == 1
        api._warn_if_still_offline()
        assert len(caplog.records) == 1
    api._cancel_failure_warning()


@pytest.mark.asyncio
async def test_suspend_cancels_pending_warning(api, caplog):
    api._get_request = AsyncMock(return_value=None)
    await api._update_product_status_endpoint_data()
    assert api._failure_warning_handle is not None
    api.suspend_polling()
    with caplog.at_level(logging.WARNING):
        api._warn_if_still_offline()
    assert not caplog.records


@pytest.mark.asyncio
async def test_resume_bypasses_backoff_and_endpoint_intervals(api):
    api._get_request = AsyncMock(return_value={"status": "ok"})
    api.suspend_polling()
    api._next_status_retry = float("inf")
    api._last_update["/counters"] = float("inf")

    api.resume_polling()
    await api._update_endpoint_data(PRODUCT_STATUS_ENDPOINT)
    await api._update_endpoint_data("/counters")

    assert api._get_request.await_count == 2
    assert not api._polling_suspended


@pytest.mark.asyncio
async def test_inflight_request_does_not_override_suspend(api):
    started = asyncio.Event()
    finish = asyncio.Event()

    async def slow_request(_endpoint):
        started.set()
        await finish.wait()
        return {"status": "ok"}

    api._get_request = AsyncMock(side_effect=slow_request)
    task = asyncio.create_task(api._update_endpoint_data(PRODUCT_STATUS_ENDPOINT))
    await started.wait()
    api.suspend_polling()
    finish.set()
    await task

    assert not api.is_online
    assert api._raw_data[PRODUCT_STATUS_ENDPOINT] is not None
    assert api._status_failure_count == 0


@pytest.mark.asyncio
async def test_repeated_suspend_is_idempotent(api, caplog):
    api._get_request = AsyncMock()
    with caplog.at_level(logging.INFO):
        api.suspend_polling()
        api.suspend_polling()
    assert sum("polling suspended" in record.message for record in caplog.records) == 1
    await api.update()
    api._get_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_before_grace_period_cancels_warning(api, caplog):
    api._get_request = AsyncMock(side_effect=[None, {"status": "ok"}])
    with caplog.at_level(logging.INFO):
        await api._update_product_status_endpoint_data()
        assert api._failure_warning_handle is not None
        api.reset_polling_backoff()
        await api._update_product_status_endpoint_data()
        assert api._failure_warning_handle is None
        assert api._status_failure_count == 0
        assert not api._failure_warning_emitted
        assert not any(record.levelno >= logging.WARNING for record in caplog.records)


@pytest.mark.asyncio
async def test_backoff_skips_status_request_until_retry(api):
    api._get_request = AsyncMock(return_value=None)
    await api._update_product_status_endpoint_data()
    assert api._next_status_retry > 0
    await api._update_product_status_endpoint_data()
    api._get_request.assert_awaited_once()
    api._cancel_failure_warning()


@pytest.mark.asyncio
async def test_recovery_after_reported_outage_logs_once(api, caplog):
    api._get_request = AsyncMock(side_effect=[None, {"status": "ok"}, {"status": "ok"}])
    with caplog.at_level(logging.INFO):
        await api._update_product_status_endpoint_data()
        api._warn_if_still_offline()
        api.reset_polling_backoff()
        await api._update_product_status_endpoint_data()
        await api._update_product_status_endpoint_data()
    assert sum("connection restored" in record.message for record in caplog.records) == 1
    api._cancel_failure_warning()
