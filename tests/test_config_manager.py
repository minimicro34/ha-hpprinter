"""Configuration manager regression tests."""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import Platform
from homeassistant.helpers.entity import EntityCategory

from custom_components.hpprinter.common.consts import DEFAULT_ENTRY_ID, DEFAULT_INTERVAL, DOMAIN
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


@pytest.mark.asyncio
async def test_initialize_with_home_assistant():
    hass = Mock()
    hass.config.language = "fr"
    entry = Mock(entry_id="printer", title="HP")
    store = Mock(async_load=AsyncMock(return_value=None), async_save=AsyncMock())
    translations = {"component.hpprinter.entity.sensor.status.name": "État"}
    with patch("custom_components.hpprinter.managers.ha_config_manager.Store", return_value=store) as factory, patch("custom_components.hpprinter.managers.ha_config_manager.translation.async_get_translations", new_callable=AsyncMock, return_value=translations) as translate:
        manager = HAConfigManager(hass, entry)
        await manager.initialize({})
    factory.assert_called_once()
    assert factory.call_args.args[0] is hass
    translate.assert_awaited_once_with(hass, "fr", "entity", {DOMAIN})
    assert manager._translations == translations
    assert manager.is_initialized


@pytest.mark.asyncio
async def test_remove_without_storage(manager):
    await manager.remove("printer")
    assert manager._store is None


@pytest.mark.parametrize("translation", [None, ""])
def test_empty_translation_fallback(manager, translation, caplog):
    description = Mock(platform=Platform.SENSOR, translation_key="status")
    description.name = "Status"
    device = Mock()
    device.name = "HP"
    manager._translations = {f"component.{DOMAIN}.entity.sensor.status.name": translation}
    assert manager.get_entity_name(description, device) == "HP Status"
    assert "Translations not found" in caplog.text


@pytest.mark.asyncio
async def test_defaults_preserve_saved_values(manager):
    manager._store = Mock(
        async_load=AsyncMock(side_effect=[
            {"printer": {"existing": 7}},
            {"printer": {"existing": 7}},
        ]),
        async_save=AsyncMock(),
    )
    with patch.object(manager, "_get_defaults", return_value={"existing": 1, "new": 2}):
        await manager._load()
    assert manager._data == {"existing": 7, "new": 2}
    manager._store.async_save.assert_awaited_once_with({"printer": {"existing": 7, "new": 2}})
    debug = manager.get_debug_data()
    assert debug["existing"] == 7
    assert debug["new"] == 2


def test_default_duration():
    assert HAConfigManager._convert_to_seconds(None) == HAConfigManager._convert_to_seconds(DEFAULT_INTERVAL)
