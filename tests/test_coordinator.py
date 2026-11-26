"""Coordinator regression tests without a running Home Assistant instance."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.hpprinter.common.consts import DOMAIN, MODEL_PROPERTY
from custom_components.hpprinter.managers.ha_coordinator import HACoordinator


@pytest.fixture
def coordinator():
    coordinator = HACoordinator.__new__(HACoordinator)
    coordinator._config_manager = Mock(entry_id="entry", entry_title="HP")
    coordinator._api = Mock()
    coordinator._devices = {}
    coordinator._main_device_data = None
    coordinator._main_device_id = None
    coordinator._parent_device_id = Mock(return_value="parent-id")
    return coordinator


def test_main_and_child_devices(coordinator):
    coordinator.create_main_device("Printer", {
        MODEL_PROPERTY: "LaserJet",
        "serial_number": "123",
        "manufacturer_name": "HP",
    }, {})
    main = coordinator.get_device("Printer")
    assert main.name == "HP"
    assert main.model == "LaserJet"
    assert main.identifiers == {(DOMAIN, "Printer")}
    coordinator.create_sub_unit_device("Network", {}, {"device_type": "Network"})
    child = coordinator.get_device("Network")
    assert child.name == "HP Network"
    assert child.via_device_id == "parent-id"
    assert child.serial_number == "123"
    coordinator.create_adapter_device("Adapter.Wifi0", {
        "hardware_config_name": "Wifi0",
        "hardware_config_device_connectivity_port_type": "EmbeddedWireless",
    }, {"device_type": "Adapter"})
    adapter = coordinator.get_device("Adapter.Wifi0")
    assert adapter.name == "HP Adapter WIFI0"
    assert adapter.model == "WIRELESS"
    assert adapter.via_device_id == "parent-id"
    assert len(coordinator.get_devices()) == 3
    assert coordinator.get_device("missing") is None


@pytest.mark.parametrize("kind,color,name,model", [
    ("toner", "Black", "HP Black Toner", "123A"),
    ("printhead", None, "HP Printhead", "Printhead"),
    (None, None, "HP", "123A"),
])
def test_consumable_device(coordinator, kind, color, name, model):
    coordinator.create_consumable_device("Consumable.K", {
        "consumable_type_enum": kind,
        "marker_color": color,
        "consumable_selectibility_number": "123A",
        "consumable_life_state_brand": "HP",
    }, {})
    device = coordinator.get_device("Consumable.K")
    assert device.name == name
    assert device.model == model
    assert device.via_device_id == "parent-id"


def test_data_access(coordinator):
    coordinator._api.data = {"Printer": {"status": "off"}}
    coordinator._api.raw_data = {"raw": {}}
    coordinator._api.data_config = {"Printer": {}}
    assert coordinator.api is coordinator._api
    assert coordinator.config_manager is coordinator._config_manager
    assert coordinator.entry_id == "entry"
    assert coordinator.entry_title == "HP"
    assert coordinator.get_device_value("Printer", "status") == "off"
    assert coordinator.get_device_value("Printer", None) == {"status": "off"}
    assert coordinator.get_device_value("missing", "status") is None
    assert coordinator.get_debug_data() == {
        "rawData": coordinator._api.raw_data,
        "devicesData": coordinator._api.data,
        "devicesConfig": coordinator._api.data_config,
    }


@pytest.mark.asyncio
async def test_update_and_failure(coordinator):
    coordinator._api.update = AsyncMock()
    coordinator._api.data = {"Printer": {"status": "off"}}
    assert await coordinator._async_update_data() == coordinator._api.data
    coordinator._api.update.assert_awaited_once()
    coordinator._api.update.side_effect = OSError("offline")
    with pytest.raises(UpdateFailed, match="offline"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_lifecycle(coordinator):
    coordinator.initialize = AsyncMock()
    coordinator._api.terminate = AsyncMock()
    await coordinator.on_home_assistant_start(Mock())
    await coordinator.on_home_assistant_stop(Mock())
    coordinator.initialize.assert_awaited_once()
    coordinator._api.terminate.assert_awaited_once()


def test_invalid_adapter_does_not_register(coordinator, caplog):
    coordinator.create_adapter_device("Adapter.invalid", {}, {})
    assert coordinator.get_device("Adapter.invalid") is None
    assert "Failed to adapter device" in caplog.text
