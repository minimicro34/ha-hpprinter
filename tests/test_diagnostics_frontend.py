"""Tests for diagnostic exports and bundled frontend registration."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.hpprinter import diagnostics, frontend
from custom_components.hpprinter.common.consts import DOMAIN


@pytest.fixture
def diagnostic_context():
    hass = Mock()
    entry = Mock(entry_id="entry", disabled_by=None, pref_disable_polling=False)
    coordinator = Mock()
    hass.data = {DOMAIN: {"entry": coordinator}}
    coordinator.get_debug_data.return_value = {"online": True}
    coordinator.get_devices.return_value = ["Main", "Adapter"]
    coordinator.get_device.side_effect = lambda key: {"identifiers": {(DOMAIN, key)}}
    coordinator.get_device_data.side_effect = lambda key: {"key": key}
    return hass, entry, coordinator


@pytest.mark.asyncio
async def test_entry_diagnostics(diagnostic_context):
    hass, entry, coordinator = diagnostic_context
    with patch.object(diagnostics, "_async_device_as_dict", side_effect=lambda h, i, d: d) as export:
        result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    assert result == {
        "disabled_by": None, "disabled_polling": False,
        "debug_data": {"online": True},
        "devices": [{"key": "Main"}, {"key": "Adapter"}],
    }
    assert export.call_count == 2


@pytest.mark.asyncio
async def test_single_device_diagnostics(diagnostic_context):
    hass, entry, coordinator = diagnostic_context
    device = Mock(identifiers={(DOMAIN, "Adapter")})
    with patch.object(diagnostics, "_async_device_as_dict", return_value={"device": {"name": "WiFi"}}) as export:
        result = await diagnostics.async_get_device_diagnostics(hass, entry, device)
    export.assert_called_once_with(hass, device.identifiers, {"key": "Adapter"})
    assert result["device"] == {"name": "WiFi"}
    assert "devices" not in result


def test_device_export_includes_disabled_and_missing_states():
    hass = Mock()
    identifiers = {(DOMAIN, "Main")}
    device = Mock(id="device", name="HP", name_by_user=None, disabled=False, disabled_by=None)
    entries = [
        Mock(entity_id="sensor.hp_status", disabled=False, disabled_by=None),
        Mock(entity_id="sensor.hp_hidden", disabled=True, disabled_by="user"),
    ]
    state = Mock()
    state.as_dict.return_value = {"state": "On", "context": {"id": "private"}}
    hass.states.get.side_effect = [state, None]
    with patch.object(diagnostics.dr, "async_get") as dr_get, patch.object(diagnostics.er, "async_get") as er_get, patch.object(diagnostics.er, "async_entries_for_device", return_value=entries) as list_entities:
        dr_get.return_value.async_get_device.return_value = device
        result = diagnostics._async_device_as_dict(hass, identifiers, {"status": "On"})
        dr_get.return_value.async_get_device.assert_called_once_with(identifiers=identifiers)
        list_entities.assert_called_once_with(er_get.return_value, device_id="device", include_disabled_entities=True)
    exported = result["device"]
    assert exported["name"] == "HP"
    assert exported["data"] == {"status": "On"}
    assert exported["entities"][0]["state"] == {"state": "On"}
    assert exported["entities"][1]["state"] is None
    assert exported["entities"][1]["disabled_by"] == "user"
    assert "context" in state.as_dict.return_value


def test_missing_registry_device():
    with patch.object(diagnostics.dr, "async_get") as dr_get, patch.object(diagnostics.er, "async_get"):
        dr_get.return_value.async_get_device.return_value = None
        assert diagnostics._async_device_as_dict(Mock(), {(DOMAIN, "missing")}, {}) == {}


@pytest.fixture
def frontend_context():
    hass = Mock()
    hass.data = {}
    hass.http.async_register_static_paths = AsyncMock()
    resources = Mock(loaded=False)
    resources.async_load = AsyncMock()
    resources.async_create_item = AsyncMock()
    resources.async_update_item = AsyncMock()
    resources.async_items.return_value = []
    return hass, resources


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [None, "yaml"])
async def test_manual_resource_mode(frontend_context, mode):
    hass, resources = frontend_context
    if mode:
        hass.data["lovelace"] = Mock(resource_mode=mode, resources=resources)
    await frontend.async_register_card(hass)
    await frontend.async_register_card(hass)
    hass.http.async_register_static_paths.assert_awaited_once()
    resources.async_load.assert_not_awaited()
    resources.async_create_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_register_new_resource(frontend_context):
    hass, resources = frontend_context
    hass.data["lovelace"] = Mock(resource_mode="storage", resources=resources)
    resources.async_items.return_value = [{"id": "other", "url": "/other.js", "res_type": "module"}]
    await frontend.async_register_card(hass)
    resources.async_load.assert_awaited_once()
    resources.async_create_item.assert_awaited_once_with({"url": frontend._CARD_URL, "res_type": "module"})
    resources.async_update_item.assert_not_awaited()
    path = hass.http.async_register_static_paths.call_args.args[0][0]
    assert path.url_path == frontend._CARD_PATH
    assert path.path.endswith("www/hpprinter-card.js")
    assert path.cache_headers is False


@pytest.mark.asyncio
@pytest.mark.parametrize("url,res_type,update", [
    (frontend._CARD_PATH + "?v=old", "module", True),
    (frontend._CARD_URL, "js", True),
    (frontend._CARD_URL, "module", False),
])
async def test_existing_resource(frontend_context, url, res_type, update):
    hass, resources = frontend_context
    resources.loaded = True
    hass.data["lovelace"] = Mock(resource_mode="storage", resources=resources)
    resources.async_items.return_value = [{"id": "card", "url": url, "res_type": res_type}]
    await frontend.async_register_card(hass)
    resources.async_load.assert_not_awaited()
    resources.async_create_item.assert_not_awaited()
    if update:
        resources.async_update_item.assert_awaited_once_with("card", {"url": frontend._CARD_URL, "res_type": "module"})
    else:
        resources.async_update_item.assert_not_awaited()
