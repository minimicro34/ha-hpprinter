"""Regression tests for integration lifecycle and discovery."""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_START, Platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components import hpprinter
from custom_components.hpprinter.common.consts import (
    DOMAIN, SIGNAL_HA_DEVICE_CREATED, SIGNAL_HA_DEVICE_DISCOVERED,
)
from custom_components.hpprinter.managers import ha_coordinator as module


@pytest.fixture
def context():
    hass = Mock()
    hass.data = {}
    entry = Mock(entry_id="entry", data={"host": "printer.local"})
    manager = Mock(entry=entry, entry_id="entry", entry_title="HP",
                   platforms=[Platform.SENSOR, Platform.BINARY_SENSOR],
                   minimum_update_interval=timedelta(seconds=10))
    manager.initialize = AsyncMock()
    manager.remove = AsyncMock()
    coordinator = Mock(config_manager=manager)
    coordinator.initialize = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    return hass, entry, manager, coordinator


@pytest.mark.asyncio
async def test_services(context):
    hass, _, _, first = context
    second = Mock()
    second.async_request_refresh = AsyncMock()
    hass.data[DOMAIN] = {"first": first, "second": second}
    with patch.object(hpprinter, "async_register_card", new_callable=AsyncMock) as register:
        assert await hpprinter.async_setup(hass, {})
    register.assert_awaited_once_with(hass)
    handlers = {call.args[1]: call.args[2] for call in hass.services.async_register.call_args_list}
    force = handlers[hpprinter.FORCE_UPDATE_SERVICE]
    suspend = handlers[hpprinter.SUSPEND_POLLING_SERVICE]
    await force(Mock(data={"entry_id": "first"}))
    first.api.resume_polling.assert_called_once()
    first.async_request_refresh.assert_awaited_once()
    second.api.resume_polling.assert_not_called()
    await suspend(Mock(data={}))
    for coordinator in (first, second):
        coordinator.api.suspend_polling.assert_called_once()
        coordinator.async_set_updated_data.assert_called_once_with(coordinator.api.data)
    with pytest.raises(ValueError, match="not loaded"):
        await force(Mock(data={"entry_id": "missing"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("running", [True, False])
async def test_setup_entry(context, running):
    hass, entry, manager, coordinator = context
    hass.is_running = running
    manager.is_initialized = True
    with patch.object(hpprinter, "HAConfigManager", return_value=manager), patch.object(hpprinter, "HACoordinator", return_value=coordinator):
        assert await hpprinter.async_setup_entry(hass, entry)
    manager.initialize.assert_awaited_once_with(entry.data)
    assert hass.data[DOMAIN]["entry"] is coordinator
    if running:
        coordinator.initialize.assert_awaited_once()
        hass.bus.async_listen_once.assert_not_called()
    else:
        coordinator.initialize.assert_not_awaited()
        hass.bus.async_listen_once.assert_called_once_with(
            EVENT_HOMEASSISTANT_START, coordinator.on_home_assistant_start
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [True, False])
async def test_setup_failure(context, raises):
    hass, entry, manager, _ = context
    manager.is_initialized = False
    if raises:
        manager.initialize.side_effect = RuntimeError("initialization failed")
    with patch.object(hpprinter, "HAConfigManager", return_value=manager), patch.object(hpprinter, "HACoordinator") as factory:
        assert not await hpprinter.async_setup_entry(hass, entry)
    factory.assert_not_called()
    assert DOMAIN not in hass.data


@pytest.mark.asyncio
async def test_unload_entry(context):
    hass, entry, manager, coordinator = context
    hass.data[DOMAIN] = {"entry": coordinator, "other": Mock()}
    hass.config_entries.async_forward_entry_unload = AsyncMock()
    assert await hpprinter.async_unload_entry(hass, entry)
    manager.remove.assert_awaited_once_with("entry")
    assert [call.args for call in hass.config_entries.async_forward_entry_unload.await_args_list] == [
        (entry, Platform.SENSOR), (entry, Platform.BINARY_SENSOR)
    ]
    assert set(hass.data[DOMAIN]) == {"other"}


@pytest.fixture
def real_coordinator(context):
    hass, entry, manager, _ = context

    def initialize_base(self, hass, *args, **kwargs):
        self.hass = hass
        self.config_entry = entry

    with patch.object(DataUpdateCoordinator, "__init__", initialize_base), patch.object(module, "RestAPIv2"), patch.object(module, "async_dispatcher_connect") as connect:
        coordinator = module.HACoordinator(hass, manager)
    connect.assert_called_once_with(hass, SIGNAL_HA_DEVICE_DISCOVERED, coordinator._on_device_discovered)
    entry.async_on_unload.assert_called_once_with(connect.return_value)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.api.initialize = AsyncMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    return coordinator


@pytest.mark.asyncio
async def test_coordinator_initialize(real_coordinator):
    coordinator = real_coordinator
    await coordinator.initialize()
    coordinator.hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        coordinator.config_manager.entry, coordinator.config_manager.platforms
    )
    coordinator.api.initialize.assert_awaited_once()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.parametrize("exists", [True, False])
def test_parent_lookup(real_coordinator, exists):
    coordinator = real_coordinator
    with patch.object(module.dr, "async_get") as registry:
        lookup = registry.return_value.async_get_device_by_identifier
        lookup.return_value = Mock(id="parent") if exists else None
        assert coordinator._parent_device_id((DOMAIN, "Main")) == ("parent" if exists else None)
        lookup.assert_called_once_with((DOMAIN, "Main"), "entry")


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["Main", "Consumable1", "Adapter1", "Scanner"])
async def test_discovery_dispatch(real_coordinator, key):
    coordinator = real_coordinator
    coordinator._device_handlers = {prefix: Mock() for prefix in ("Main", "Consumable", "Adapter")}
    coordinator.create_sub_unit_device = Mock()
    coordinator.hass.create_task.side_effect = lambda coro: coro.close()
    data, config = {"value": 1}, {"device_type": "test"}
    with patch.object(module, "async_dispatcher_send") as send:
        await coordinator._on_device_discovered("other", key, data, config)
        send.assert_not_called()
        coordinator.hass.create_task.assert_not_called()
        await coordinator._on_device_discovered("entry", key, data, config)
        send.assert_called_once_with(coordinator.hass, SIGNAL_HA_DEVICE_CREATED, "entry", key, data, config)
    handler = next((handler for prefix, handler in coordinator._device_handlers.items() if key.startswith(prefix)), coordinator.create_sub_unit_device)
    handler.assert_called_once_with(key, data, config)
    coordinator.hass.create_task.assert_called_once()


@pytest.mark.parametrize("method", ["create_main_device", "create_sub_unit_device", "create_consumable_device"])
def test_device_creation_failure(real_coordinator, method, caplog):
    coordinator = real_coordinator
    coordinator._main_device_data = {}
    with patch.object(coordinator, "_parent_device_id", return_value="parent"), patch.object(module, "DeviceInfo", side_effect=ValueError("invalid device")) as factory:
        getattr(coordinator, method)("invalid", {}, {})
    factory.assert_called_once()
    assert "invalid" not in coordinator.get_devices()
    assert "invalid device" in caplog.text
