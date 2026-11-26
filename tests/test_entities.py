"""Regression tests for HP Printer entities."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import ATTR_STATE, Platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.hpprinter import binary_sensor, sensor
from custom_components.hpprinter.common import base_entity
from custom_components.hpprinter.common.consts import DOMAIN
from custom_components.hpprinter.common.entity_descriptions import (
    IntegrationBinarySensorEntityDescription,
    IntegrationSensorEntityDescription,
)


@pytest.fixture
def coordinator():
    coordinator = Mock()
    coordinator.config_manager.config_data.hostname = "printer.local"
    coordinator.config_manager.get_entity_name.return_value = "HP Test"
    coordinator.get_device.return_value = DeviceInfo(name="HP")
    coordinator.get_device_data.return_value = {"value": "42"}
    coordinator.get_device_value.return_value = "42"
    return coordinator


@pytest.mark.parametrize("value,kwargs,expected", [
    ("42.5", {"native_unit_of_measurement": "%"}, 42.5),
    ("42", {"native_unit_of_measurement": "pages"}, 42),
    ("42", {"state_class": SensorStateClass.TOTAL_INCREASING}, 42),
    ("4.2", {"state_class": SensorStateClass.MEASUREMENT}, 4.2),
    ("READY", {"device_class": SensorDeviceClass.ENUM}, "ready"),
    ("2026-11-26", {"device_class": SensorDeviceClass.DATE}, datetime(2026, 11, 26)),
    ("raw", {}, "raw"),
    (None, {}, None),
])
def test_sensor_values(coordinator, value, kwargs, expected):
    coordinator.get_device_value.return_value = value
    description = IntegrationSensorEntityDescription(
        key="value", device_type="Main", icon="mdi:printer", **kwargs
    )
    entity = sensor.HASensorEntity(description, coordinator, "Main")
    assert entity.native_value == expected
    assert type(entity.native_value) is type(expected)
    assert entity.name == "HP Test"
    assert entity.unique_id == "hpprinter_printer_local_main_sensor_value"
    assert entity.icon == "mdi:printer"
    assert entity.device_info == coordinator.get_device.return_value
    assert entity.local_coordinator is coordinator
    assert entity.get_data() == {"value": "42"}
    coordinator.get_device_value.assert_called_with("Main", "value")


def test_timestamp_preserves_instant(coordinator):
    value = "2026-11-26T10:00:00+01:00"
    coordinator.get_device_value.return_value = value
    description = IntegrationSensorEntityDescription(
        key="value", device_class=SensorDeviceClass.TIMESTAMP
    )
    entity = sensor.HASensorEntity(description, coordinator, "Main")
    assert entity.native_value.timestamp() == datetime.fromisoformat(value).timestamp()


@pytest.mark.parametrize("value,expected", [("ON", True), ("off", False), (None, False)])
def test_binary_values(coordinator, value, expected):
    coordinator.get_device_value.return_value = value
    description = IntegrationBinarySensorEntityDescription(
        key="value", on_values=["on", "ready"]
    )
    entity = binary_sensor.HABinarySensorEntity(description, coordinator, "Main")
    assert entity.is_on is expected
    assert entity.extra_state_attributes == {ATTR_STATE: value}


def test_coordinator_updates_entities(coordinator):
    numeric = sensor.HASensorEntity(
        IntegrationSensorEntityDescription(key="value", native_unit_of_measurement="pages"),
        coordinator, "Main",
    )
    binary = binary_sensor.HABinarySensorEntity(
        IntegrationBinarySensorEntityDescription(key="value", on_values=["42"]),
        coordinator, "Main",
    )
    assert binary.is_on
    coordinator.get_device_value.return_value = "43"
    with patch.object(CoordinatorEntity, "_handle_coordinator_update") as update:
        numeric._handle_coordinator_update()
        binary._handle_coordinator_update()
    assert numeric.native_value == 43
    assert not binary.is_on
    assert binary.extra_state_attributes == {ATTR_STATE: "43"}
    assert update.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("module,platform,entity_type", [
    (sensor, Platform.SENSOR, sensor.HASensorEntity),
    (binary_sensor, Platform.BINARY_SENSOR, binary_sensor.HABinarySensorEntity),
])
async def test_platform_setup(module, platform, entity_type):
    hass, entry, add = Mock(), Mock(), Mock()
    with patch.object(module, "async_setup_base_entry", new_callable=AsyncMock) as setup:
        await module.async_setup_entry(hass, entry, add)
    setup.assert_awaited_once_with(hass, entry, platform, entity_type, add)


@pytest.mark.asyncio
async def test_dispatcher_filters_entries(coordinator):
    hass = Mock()
    hass.data = {DOMAIN: {"entry": coordinator}}
    entry = Mock(entry_id="entry")
    add = Mock()
    with patch.object(base_entity, "async_dispatcher_connect") as connect:
        await base_entity.async_setup_base_entry(
            hass, entry, Platform.SENSOR, sensor.HASensorEntity, add
        )
    handler = connect.call_args.args[2]
    entry.async_on_unload.assert_called_once_with(connect.return_value)
    with patch.object(base_entity, "_async_handle_device_created") as create:
        handler("other", "Main", {}, {})
        create.assert_not_called()
        handler("entry", "Main", {}, {"device_type": "Main"})
        create.assert_called_once_with(
            coordinator, Platform.SENSOR, sensor.HASensorEntity, add,
            "Main", {}, {"device_type": "Main"},
        )


def test_creation_continues_after_invalid_entity(coordinator, caplog):
    good = IntegrationSensorEntityDescription(key="good")
    bad = IntegrationSensorEntityDescription(key="bad")
    coordinator.config_manager.get_entity_descriptions.return_value = [bad, good]
    entity = Mock(unique_id="good")
    factory = Mock(side_effect=[ValueError("invalid"), entity])
    add = Mock()
    base_entity._async_handle_device_created(
        coordinator, Platform.SENSOR, factory, add, "Main", {}, {"device_type": "Main"}
    )
    add.assert_called_once_with([entity], True)
    assert "Failed to initialize sensor.bad" in caplog.text
    coordinator.config_manager.get_entity_descriptions.return_value = []
    add.reset_mock()
    base_entity._async_handle_device_created(
        coordinator, Platform.SENSOR, factory, add, "Main", {}, {"device_type": "Main"}
    )
    add.assert_not_called()
