"""Register the bundled HP Printer Lovelace card."""

import asyncio
import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
_CARD_PATH = "/hpprinter/hpprinter-card.js"
_VERSION = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))["version"]
_CARD_URL = f"{_CARD_PATH}?v={_VERSION}"
_LOCK_KEY = "hpprinter_frontend_lock"
_PATH_KEY = "hpprinter_frontend_path_registered"


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card and register/update one Lovelace storage resource."""
    async with hass.data.setdefault(_LOCK_KEY, asyncio.Lock()):
        if not hass.data.get(_PATH_KEY):
            await hass.http.async_register_static_paths(
                [StaticPathConfig(
                    _CARD_PATH,
                    str(Path(__file__).parent / "www" / "hpprinter-card.js"),
                    False,
                )]
            )
            hass.data[_PATH_KEY] = True

        lovelace = hass.data.get("lovelace")
        if lovelace is None or getattr(lovelace, "resource_mode", None) != "storage":
            _LOGGER.info("Lovelace storage resources unavailable; add %s manually", _CARD_URL)
            return

        resources = lovelace.resources
        if not resources.loaded:
            await resources.async_load()

        matches = [
            item for item in resources.async_items()
            if urlsplit(item["url"]).path == _CARD_PATH
        ]
        for item in matches:
            if item["url"] != _CARD_URL or item.get("res_type") != "module":
                await resources.async_update_item(
                    item["id"], {"url": _CARD_URL, "res_type": "module"}
                )
        if not matches:
            await resources.async_create_item({"url": _CARD_URL, "res_type": "module"})
