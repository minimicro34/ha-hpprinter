"""Regression tests for HP Printer service actions."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.hpprinter import async_setup
from custom_components.hpprinter.common.consts import DOMAIN


@pytest.mark.asyncio
async def test_suspend_service_notifies_coordinator_entities():
    coordinator = Mock()
    coordinator.api.data = {"Printer": {"TotalImpressions": "1945"}}
    coordinator.async_set_updated_data = Mock()
    hass = Mock()
    hass.data = {DOMAIN: {"entry-1": coordinator}}
    handlers = {}

    def register(_domain, name, handler, **_kwargs):
        handlers[name] = handler

    hass.services.async_register.side_effect = register

    with patch(
        "custom_components.hpprinter.async_register_card", new_callable=AsyncMock
    ):
        assert await async_setup(hass, {}) is True

    await handlers["suspend_polling"](Mock(data={"entry_id": "entry-1"}))

    coordinator.api.suspend_polling.assert_called_once_with()
    coordinator.async_set_updated_data.assert_called_once_with(
        coordinator.api.data
    )
    coordinator.async_request_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_force_update_resumes_and_refreshes_target():
    coordinator = Mock()
    coordinator.async_request_refresh = AsyncMock()
    hass = Mock()
    hass.data = {DOMAIN: {"entry-1": coordinator}}
    handlers = {}

    def register(_domain, name, handler, **_kwargs):
        handlers[name] = handler

    hass.services.async_register.side_effect = register

    with patch(
        "custom_components.hpprinter.async_register_card", new_callable=AsyncMock
    ):
        assert await async_setup(hass, {}) is True

    await handlers["force_update"](Mock(data={"entry_id": "entry-1"}))

    coordinator.api.resume_polling.assert_called_once_with()
    coordinator.async_request_refresh.assert_awaited_once_with()
