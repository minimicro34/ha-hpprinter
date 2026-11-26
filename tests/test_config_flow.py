"""Regression tests for configuration and options flows."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SSL

from custom_components.hpprinter import config_flow
from custom_components.hpprinter.common.consts import (
    DEFAULT_NAME, MODEL_PROPERTY, PRINTER_MAIN_DEVICE, PRODUCT_MAIN_ENDPOINT,
)
from custom_components.hpprinter.managers import flow_manager
from custom_components.hpprinter.models import AlreadyExistsError, LoginError
from custom_components.hpprinter.models.config_data import ConfigData


INPUT = {CONF_HOST: "printer.local", CONF_PORT: 443, CONF_SSL: True}


@pytest.fixture
def flow():
    hass = Mock()
    handler = Mock()
    with patch.object(flow_manager, "HAConfigManager"):
        manager = flow_manager.IntegrationFlowManager(hass, handler)
    manager._config_manager.initialize = AsyncMock()
    return manager, handler, hass


@pytest.mark.asyncio
async def test_initial_form(flow):
    manager, handler, _ = flow
    assert await manager.async_step() is handler.async_show_form.return_value
    args = handler.async_show_form.call_args.kwargs
    assert args["step_id"] == "user"
    assert args["errors"] is None
    assert args["data_schema"](INPUT) == INPUT
    manager._config_manager.initialize.assert_not_awaited()


@pytest.mark.asyncio
async def test_options_form(flow):
    manager, handler, _ = flow
    manager._entry = Mock(data=INPUT, title="Existing HP")
    manager._flow_id = "init"
    await manager.async_step()
    args = handler.async_show_form.call_args.kwargs
    assert args["step_id"] == "init"
    assert args["data_schema"]({}) == INPUT


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["LaserJet", None])
async def test_successful_connection(flow, model):
    manager, handler, _ = flow
    with patch.object(flow_manager, "RestAPIv2") as factory:
        api = factory.return_value
        api.initialize = AsyncMock()
        api.update = AsyncMock()
        api.is_online = True
        api.config_data.hostname = INPUT[CONF_HOST]
        api.data = {PRINTER_MAIN_DEVICE: {MODEL_PROPERTY: model}} if model else {}
        result = await manager.async_step(INPUT)
    assert result is handler.async_create_entry.return_value
    manager._config_manager.initialize.assert_awaited_once_with(INPUT)
    api.initialize.assert_awaited_once()
    api.update.assert_awaited_once_with([PRODUCT_MAIN_ENDPOINT])
    handler.async_create_entry.assert_called_once_with(
        title=f"{model or DEFAULT_NAME} (printer.local)", data=INPUT
    )
    assert handler.async_create_entry.call_args.kwargs["data"] is not INPUT


@pytest.mark.asyncio
@pytest.mark.parametrize("raises,error", [(False, "error_404"), (True, "error_400")])
async def test_connection_failure(flow, raises, error):
    manager, handler, _ = flow
    with patch.object(flow_manager, "RestAPIv2") as factory:
        api = factory.return_value
        api.initialize = AsyncMock(side_effect=OSError("network") if raises else None)
        api.is_online = False
        api.update = AsyncMock()
        await manager.async_step(INPUT)
    handler.async_create_entry.assert_not_called()
    api.update.assert_not_awaited()
    args = handler.async_show_form.call_args.kwargs
    assert args["errors"] == {"base": error}
    assert args["data_schema"]({}) == INPUT


@pytest.mark.asyncio
async def test_options_update_preserves_title(flow):
    manager, handler, hass = flow
    entry = Mock(data=INPUT, title="Existing HP")
    manager._entry = entry
    manager._flow_id = "init"
    changed = {**INPUT, CONF_PORT: 8443, "extra": True}
    with patch.object(flow_manager, "RestAPIv2") as factory:
        api = factory.return_value
        api.initialize = AsyncMock()
        api.update = AsyncMock()
        api.is_online = True
        api.data = {}
        await manager.async_step(changed)
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, data={**INPUT, CONF_PORT: 8443}, title="Existing HP"
    )
    handler.async_create_entry.assert_called_once_with(
        title="Existing HP", data={"extra": True}
    )


@pytest.mark.asyncio
async def test_flow_handlers_delegate():
    entry = Mock()
    handler = config_flow.DomainFlowHandler()
    handler.hass = Mock()
    options = handler.async_get_options_flow(entry)
    options.hass = handler.hass
    with patch.object(config_flow, "IntegrationFlowManager") as factory:
        factory.return_value.async_step = AsyncMock()
        await handler.async_step_user(INPUT)
        factory.assert_called_once_with(handler.hass, handler)
        factory.return_value.async_step.assert_awaited_once_with(INPUT)
        factory.reset_mock()
        await options.async_step_init(INPUT)
        factory.assert_called_once_with(options.hass, options, entry)
        factory.return_value.async_step.assert_awaited_once_with(INPUT)


@pytest.mark.parametrize("ssl,port,url", [
    (True, 443, "https://printer.local:443"),
    ("true", 8443, "https://printer.local:8443"),
    (False, None, "http://printer.local:80"),
])
def test_connection_settings(ssl, port, url):
    config = ConfigData()
    config.update({CONF_HOST: "printer.local", CONF_PORT: port, CONF_SSL: ssl})
    assert config.url == url
    assert config.hostname == "printer.local"
    assert config.port == (port or 80)
    assert config.is_ssl is (str(ssl).lower() == "true")
    assert repr(config) == str(config.to_dict())


def test_schema_defaults():
    schema = ConfigData.default_schema(None)
    assert schema({CONF_HOST: "printer.local"}) == {
        CONF_HOST: "printer.local", CONF_PORT: 80, CONF_SSL: False,
    }


def test_configuration_errors():
    entry = Mock()
    assert AlreadyExistsError(entry).entry is entry
    assert LoginError({"base": "invalid"}).errors == {"base": "invalid"}
