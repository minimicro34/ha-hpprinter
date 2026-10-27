import logging
import sys

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_START
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .common.consts import DEFAULT_NAME, DOMAIN
from .frontend import async_register_card
from .managers.ha_config_manager import HAConfigManager
from .managers.ha_coordinator import HACoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
FORCE_UPDATE_SERVICE = "force_update"
FORCE_UPDATE_SCHEMA = vol.Schema({vol.Optional("entry_id"): cv.string})


async def async_setup(hass, _config):
    await async_register_card(hass)

    async def async_force_update(call: ServiceCall) -> None:
        """Force immediate polling, bypassing backoff and endpoint intervals."""
        coordinators = hass.data.get(DOMAIN, {})
        entry_id = call.data.get("entry_id")
        targets = (
            [coordinators[entry_id]]
            if entry_id in coordinators
            else list(coordinators.values()) if entry_id is None else []
        )
        if entry_id is not None and not targets:
            raise ValueError(f"HP Printer config entry not loaded: {entry_id}")
        for coordinator in targets:
            coordinator.api.reset_polling_backoff()
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        FORCE_UPDATE_SERVICE,
        async_force_update,
        schema=FORCE_UPDATE_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Shinobi Video component."""
    initialized = False

    try:
        entry_config = {key: entry.data[key] for key in entry.data}

        config_manager = HAConfigManager(hass, entry)
        await config_manager.initialize(entry_config)

        is_initialized = config_manager.is_initialized

        if is_initialized:
            coordinator = HACoordinator(hass, config_manager)

            hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

            if hass.is_running:
                await coordinator.initialize()

            else:
                hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_START, coordinator.on_home_assistant_start
                )

            _LOGGER.info("Finished loading integration")

        initialized = is_initialized

    except Exception as ex:  # noqa: BLE001 - report device or API failures
        tb = sys.exc_info()[2]
        line_number = tb.tb_lineno

        _LOGGER.error(
            f"Failed to load {DEFAULT_NAME}, error: {ex}, line: {line_number}"
        )

    return initialized


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    _LOGGER.info(f"Unloading {DOMAIN} integration, Entry ID: {entry.entry_id}")

    coordinator: HACoordinator = hass.data[DOMAIN][entry.entry_id]

    await coordinator.config_manager.remove(entry.entry_id)

    platforms = coordinator.config_manager.platforms

    for platform in platforms:
        await hass.config_entries.async_forward_entry_unload(entry, platform)

    del hass.data[DOMAIN][entry.entry_id]

    return True
