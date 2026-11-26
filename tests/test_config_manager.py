"""Configuration manager regression tests."""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.const import Platform
from homeassistant.helpers.entity import EntityCategory

from custom_components.hpprinter.common.consts import DEFAULT_ENTRY_ID
from custom_components.hpprinter.managers.ha_config_manager import HAConfigManager


@pytest.fixture
def manager():
    return HAConfigManager(None, Mock(entry_id="printer", title="HP"))


@pytest.mark.asyncio
async def test_initialize_real_parameters(manager):
    await manager.initialize({})
    assert manager.is_initialized
    assert manager.entry_id == "printer"
    assert manager.entry_title == "HP"
    assert manager.entry.entry_id == "printer"
    assert manager.config_data is not None
    assert manager.data_points
    assert manager.endpoints
    assert manager.minimum_update_interval == timedelta(
        seconds=min(manager.get_update_interval(uri) for uri in manager.endpoints)
    )
    assert Platform.SENSOR in manager.platforms
    assert Platform.BINARY_SENSOR in manager.platforms
    assert manager.get_update_interval("/unknown") == manager._default_update_interval
    assert isinstance(manager.get_debug_data(), dict)


@pytest.mark.parametrize("duration,seconds", [("10s", 10), ("2m", 120), ("1h", 3600)])
def test_duration(duration, seconds):
    assert HAConfigManager._convert_to_seconds(duration) == seconds


@pytest.mark.asyncio
async def test_store_preserves_other_entries(manager):
    manager._store = Mock()
    manager._store.async_load = AsyncMock(return_value={
        "printer": {"old": 1}, "other": {"keep": True}, DEFAULT_ENTRY_ID: {},
    })
    manager._store.async_save = AsyncMock()
    await manager._load()
    assert manager._data == {"old": 1}
    assert manager._store.async_save.await_args.args[0] == {
        "printer": {"old": 1}, "other": {"keep": True},
    }
    manager._store.async_load.return_value = {"printer": {"old": 1}, "other": {}}
    manager._data = {"old": 2}
    await manager._save()
    assert manager._store.async_save.await_args.args[0]["printer"] == {"old": 2}
    await manager.remove("printer")
    assert manager._store.async_save.await_args.args[0] == {"other": {}}


@pytest.mark.asyncio
async def test_empty_store_and_no_change(manager):
    manager._store = Mock(async_load=AsyncMock(return_value=None),
                          async_save=AsyncMock())
    await manager._load()
    assert manager._data == {}
    manager._store.async_save.assert_not_awaited()
    await manager.remove("missing")
    manager._store.async_save.assert_not_awaited()
    manager._data = {"new": 1}
    await manager._save()
    manager._store.async_save.assert_awaited_once_with({"printer": {"new": 1}})


@pytest.mark.parametrize("endpoint,valid", [
    ({"uri": "/Status.xml", "type": "ok"}, True),
    ({"uri": "/Blocked.xml", "type": "ok"}, False),
    ({"uri": "/Status.xml", "type": "blocked"}, False),
    ({"uri": "/StatusCap.xml", "type": "ok"}, False),
    ({"uri": "/Status/{id}", "type": "ok"}, False),
    ({"uri": "/Status.xml", "type": "ok", "methods": ["post"]}, False),
])
def test_endpoint_validation(manager, endpoint, valid):
    manager._exclude_uri_list = ["/Blocked.xml"]
    manager._exclude_type_list = ["blocked"]
    assert manager.is_valid_endpoint(endpoint) is valid


def test_entity_descriptions_and_exclusions(manager):
    manager._data_points = [{
        "device_type": "Printer",
        "properties": {
            "count": {"platform": "sensor", "unit_of_measurement": "pages",
                      "entity_category": "diagnostic", "exclude": {"mode": ["hidden"]}},
            "ready": {"platform": "binary_sensor", "on_values": ["ON", "Ready"],
                      "exclude": {"mode": "disabled"}},
            "internal": {"path": "Internal"},
        },
    }]
    manager._load_entity_descriptions()
    assert set(manager.platforms) == {Platform.SENSOR, Platform.BINARY_SENSOR}
    data = {"count": 5, "ready": "ON"}
    sensor, = manager.get_entity_descriptions(Platform.SENSOR, "Printer", data)
    binary, = manager.get_entity_descriptions(Platform.BINARY_SENSOR, "Printer", data)
    assert sensor.native_unit_of_measurement == "pages"
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC
    assert binary.on_values == ["on", "ready"]
    assert not manager.get_entity_descriptions(Platform.SENSOR, "Other", data)
    assert not manager.get_entity_descriptions(Platform.SENSOR, "Printer", {})
    assert not manager.get_entity_descriptions(
        Platform.SENSOR, "Printer", {**data, "mode": "hidden"}
    )
    assert not manager.get_entity_descriptions(
        Platform.BINARY_SENSOR, "Printer", {**data, "mode": "disabled"}
    )
    manager._update_platforms()
    assert len(manager.platforms) == 2
