import asyncio
import json
import logging
import sys
import time
from datetime import datetime

import xmltodict
from aiohttp import ClientResponseError, ClientSession, ClientTimeout, TCPConnector
from defusedxml import ElementTree
from flatten_json import flatten
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify, ssl
from homeassistant.util.ssl import SSLCipherList

from ..common.consts import (
    IGNORED_KEYS,
    PRODUCT_STATUS_ENDPOINT,
    PRODUCT_STATUS_OFFLINE_PAYLOAD,
    SIGNAL_HA_DEVICE_DISCOVERED,
)
from ..models.config_data import ConfigData
from .ha_config_manager import HAConfigManager

_LOGGER = logging.getLogger(__name__)


class RestAPIv2:
    def __init__(self, hass, config_manager: HAConfigManager):
        self._loop = hass.loop if hass else None
        self._config_manager = config_manager
        self._hass = hass
        self._endpoints = self._config_manager.endpoints

        self._session: ClientSession | None = None

        self._data: dict = {}
        self._data_config: dict = {}
        self._last_update: dict[str, float] = {}

        self._raw_data: dict = {}

        self._device_dispatched: list[str] = []
        self._support_prefetch: bool = False

        self._is_online: bool = False
        self._status_failure_count = 0
        self._polling_suspended = False
        self._failure_warning_handle = None
        self._failure_warning_emitted = False
        self._next_status_retry = 0.0
        self._last_status_failure: str | None = None
        self._secondary_timeout_counts: dict[str, int] = {}
        self._cache_store = (
            Store(hass, 1, f"hpprinter.{config_manager.entry_id}.cache")
            if hass is not None
            else None
        )
        self._cache_dirty = False
        self._last_successful_update: float | None = None
        self._last_persisted_success: float | None = None

    @property
    def data(self) -> dict | None:
        return self._data

    @property
    def data_config(self) -> dict | None:
        return self._data_config

    @property
    def raw_data(self) -> dict | None:
        return self._raw_data

    @property
    def config_data(self) -> ConfigData | None:
        if self._config_manager is not None:
            return self._config_manager.config_data

        return None

    @property
    def is_online(self) -> bool:
        return self._is_online

    def _cancel_failure_warning(self):
        if self._failure_warning_handle is not None:
            self._failure_warning_handle.cancel()
            self._failure_warning_handle = None

    def _warn_if_still_offline(self):
        self._failure_warning_handle = None
        if (
            self._polling_suspended
            or not self._status_failure_count
            or self._is_online
            or self._failure_warning_emitted
        ):
            return
        self._failure_warning_emitted = True
        _LOGGER.warning(
            "HP Printer %s unreachable (%s); exponential backoff active",
            self.config_data.hostname,
            self._last_status_failure or "no response",
        )

    def suspend_polling(self):
        """Stop network polling without unloading entities or cached values."""
        if self._polling_suspended:
            return
        self._polling_suspended = True
        self._cancel_failure_warning()
        self._failure_warning_emitted = False
        self._status_failure_count = 0
        self._next_status_retry = 0.0
        self._is_online = False
        self._raw_data[PRODUCT_STATUS_ENDPOINT] = PRODUCT_STATUS_OFFLINE_PAYLOAD
        if self._raw_data:
            self._extract_data(self._get_devices_data())
        _LOGGER.info("HP Printer %s polling suspended", self.config_data.hostname)

    def resume_polling(self):
        """Resume polling and allow an immediate full refresh."""
        was_suspended = self._polling_suspended
        self._polling_suspended = False
        self.reset_polling_backoff()
        if was_suspended:
            _LOGGER.info(
                "HP Printer %s polling resumed; forcing refresh",
                self.config_data.hostname,
            )

    async def terminate(self):
        self._cancel_failure_warning()
        _LOGGER.info("Terminating session to HP Printer EWS")

        if self._session is not None:
            await self._session.close()

            self._session = None

    async def initialize(self):
        if self._cache_store is not None:
            cached = await self._cache_store.async_load()
            if isinstance(cached, dict):
                self._raw_data = {
                    endpoint: payload
                    for endpoint, payload in cached.get("endpoints", {}).items()
                    if endpoint != PRODUCT_STATUS_ENDPOINT
                }
                self._last_successful_update = cached.get("last_successful_update")
                self._last_persisted_success = self._last_successful_update

        try:
            if self._session is None:
                if self._hass is None:
                    self._session = ClientSession(loop=self._loop)
                else:
                    self._session = async_create_clientsession(hass=self._hass)

            await self._update_product_status_endpoint_data()

        except Exception as ex:  # noqa: BLE001 - report device or API failures
            tb = sys.exc_info()[2]
            line_number = tb.tb_lineno

            _LOGGER.warning(
                f"Failed to initialize session, Error: {ex}, Line: {line_number}"
            )

    def _get_ssl_connector(self):
        ssl_context = ssl.create_no_verify_ssl_context(SSLCipherList.INTERMEDIATE)

        connector = TCPConnector(
            loop=self._loop,
            enable_cleanup_closed=True,  # Hardcoded op True aangezien de constante weg is
            ssl=ssl_context,
        )

        return connector

    async def _update_endpoint_data(self, endpoint: str) -> bool:
        can_update = False

        try:
            now = datetime.now()
            now_ts = now.timestamp()

            if self._polling_suspended:
                return False

            if (
                endpoint == PRODUCT_STATUS_ENDPOINT
                and time.monotonic() < self._next_status_retry
            ):
                return False

            last_update = self._last_update.get(endpoint, 0)

            last_update_diff = int(now_ts - last_update)
            interval = self._config_manager.get_update_interval(endpoint)

            can_update = last_update_diff >= interval

            if can_update:
                data = await self._get_request(endpoint)
                if self._polling_suspended:
                    return False
                if endpoint == PRODUCT_STATUS_ENDPOINT:
                    if data is None:
                        self._status_failure_count += 1
                        delay = min(
                            300, 10 * 2 ** min(self._status_failure_count - 1, 5)
                        )
                        self._next_status_retry = time.monotonic() + delay
                        if self._status_failure_count == 1:
                            self._cancel_failure_warning()
                            self._failure_warning_emitted = False
                            self._failure_warning_handle = (
                                asyncio.get_running_loop().call_later(
                                    10, self._warn_if_still_offline
                                )
                            )
                        # Repeated failures are silent at all log levels.
                    else:
                        self._cancel_failure_warning()
                        if self._failure_warning_emitted:
                            _LOGGER.info(
                                "HP Printer %s connection restored after %d failed attempts",
                                self.config_data.hostname,
                                self._status_failure_count,
                            )
                        self._failure_warning_emitted = False
                        self._status_failure_count = 0
                        self._next_status_retry = 0.0
                        self._last_status_failure = None

                # Preserve the last successful payload for non-status endpoints.
                # A failed request must not erase counters or consumable data.
                if data is not None or endpoint == PRODUCT_STATUS_ENDPOINT:
                    self._raw_data[endpoint] = data
                    self._last_update[endpoint] = now_ts
                    if data is not None:
                        self._last_successful_update = now_ts
                        if endpoint != PRODUCT_STATUS_ENDPOINT or (
                            self._last_persisted_success is None
                            or now_ts - self._last_persisted_success >= 300
                        ):
                            self._cache_dirty = True

        except Exception as ex:  # noqa: BLE001 - report device or API failures
            tb = sys.exc_info()[2]
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to update endpoint {endpoint} data, Error: {ex}, Line: {line_number}"
            )

        return can_update

    async def _update_product_status_endpoint_data(self) -> bool:
        was_changed = False

        try:
            status_endpoint = PRODUCT_STATUS_ENDPOINT

            was_online = self.is_online
            was_updated = await self._update_endpoint_data(status_endpoint)

            if was_updated:
                product_status_data = self._raw_data.get(status_endpoint)
                self._is_online = product_status_data is not None

                if not self._is_online:
                    self._raw_data[status_endpoint] = PRODUCT_STATUS_OFFLINE_PAYLOAD

                was_changed = self._is_online != was_online

            if was_changed:
                _LOGGER.debug(f"Device online state changed to {self._is_online}")

                got_online = not was_online and self._is_online

                if got_online:
                    for endpoint in self._last_update:
                        if endpoint != PRODUCT_STATUS_ENDPOINT:
                            self._last_update[endpoint] = 0

        except Exception as ex:  # noqa: BLE001 - report device or API failures
            tb = sys.exc_info()[2]
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to update product status data, Error: {ex}, Line: {line_number}"
            )

        return was_changed

    def reset_polling_backoff(self):
        """Allow the next update to probe the printer and refresh all endpoints."""
        self._next_status_retry = 0.0
        self._last_update.clear()

    async def update(self, endpoints: list[str] | None = None):
        try:
            if self._polling_suspended:
                return

            _LOGGER.debug(f"Updating data from {self.config_data.hostname}")

            was_changed = await self._update_product_status_endpoint_data()
            update_counter = 1 if was_changed else 0

            if self._is_online and not self._polling_suspended:
                if endpoints is None:
                    endpoints = self._config_manager.endpoints

                for endpoint in endpoints:
                    if self._polling_suspended:
                        break
                    was_updated = await self._update_endpoint_data(endpoint)

                    if was_updated:
                        update_counter += 1

            if self._cache_dirty and self._cache_store is not None:
                await self._cache_store.async_save(
                    {
                        "endpoints": {
                            key: value
                            for key, value in self._raw_data.items()
                            if key != PRODUCT_STATUS_ENDPOINT and value is not None
                        },
                        "last_successful_update": self._last_successful_update,
                    }
                )
                self._cache_dirty = False
                self._last_persisted_success = self._last_successful_update

            if update_counter > 0 or (self._raw_data and not self._data):
                devices = self._get_devices_data()

                self._extract_data(devices)

        except Exception as ex:  # noqa: BLE001 - report device or API failures
            tb = sys.exc_info()[2]
            line_number = tb.tb_lineno

            _LOGGER.error(f"Failed to update data, Error: {ex}, Line: {line_number}")

    def _extract_data(self, devices: list[dict]):
        device_data = {}
        device_config = {}

        for item in devices:
            item_config = item.get("config")
            item_data = item.get("data")

            device_type = item_config.get("device_type")
            identifier = item_config.get("identifier")
            properties = item_config.get("properties")
            flat = item_config.get("flat", False)

            device_key = device_type

            if identifier is not None:
                identifier_key = identifier.get("key")
                identifier_mapping = identifier.get("mapping")

                key_data = item_data.get(identifier_key)

                device_id = (
                    item_data.get(identifier_key)
                    if identifier_mapping is None
                    else identifier_mapping.get(key_data)
                )

                if flat:
                    new_items_data = {
                        slugify(f"{device_id}_{key}"): item_data[key]
                        for key in item_data
                        if key != identifier_key
                    }

                    new_properties = {
                        slugify(f"{device_id}_{key}"): properties[key]
                        for key in properties
                        if key != identifier_key
                    }

                    item_data = new_items_data
                    properties = new_properties

                else:
                    device_key = f"{device_type}.{device_id}"

            data = device_data.get(device_key, {})

            has_data = len(list(item_data.keys())) > 0
            data.update(item_data)

            if has_data:
                device_data[device_key] = data

                if device_key in device_config:
                    config = device_config[device_key]
                    config["properties"].update(properties)

                else:
                    device_config[device_key] = {
                        "device_type": device_type,
                        "properties": properties,
                    }

        self._data_config = device_config
        self._data = device_data

        for device_key in self._data:
            self.device_data_changed(device_key)

    @staticmethod
    def _get_device_from_list(
        data: list[dict], identifier_key: str, device_id
    ) -> dict | None:
        data_items = [
            data_item
            for data_item in data
            if data_item.get(identifier_key) == device_id
        ]

        if data_items:
            return data_items[0]

        else:
            return None

    def _get_device_config(self, device_type: str) -> dict | None:
        data_configs = [
            data_point
            for data_point in self._config_manager.data_points
            if device_type == data_point.get("name")
        ]

        if data_configs:
            return data_configs[0]

        else:
            return None

    @staticmethod
    def _get_data_section(data: dict, path: str) -> dict:
        path_parts = path.split(".")
        result = data

        if result is not None:
            for path_part in path_parts:
                result = result.get(path_part)

        return result

    @staticmethod
    def _find_media_type_entries(node):
        """Locate media-type usage entries regardless of their XML parent."""
        matches = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "UsageByMediaType":
                    entries = value if isinstance(value, list) else [value]
                    matches.extend(
                        entry for entry in entries if isinstance(entry, dict)
                    )
                else:
                    matches.extend(RestAPIv2._find_media_type_entries(value))
        elif isinstance(node, list):
            for item in node:
                matches.extend(RestAPIv2._find_media_type_entries(item))
        return matches

    def _get_devices_data(self):
        devices = []

        for data_point in self._config_manager.data_points:
            endpoint = data_point.get("endpoint")
            path = data_point.get("path")
            properties = data_point.get("properties")

            if endpoint is not None:
                data_item = self._raw_data.get(endpoint)

                data = (
                    self._find_media_type_entries(data_item)
                    if data_point.get("recursive_media_type")
                    else self._get_data_section(data_item, path)
                )
                if (
                    data_point.get("name") == "Status"
                    and self._last_successful_update is not None
                ):
                    timestamp = (
                        datetime.fromtimestamp(self._last_successful_update)
                        .astimezone()
                        .isoformat()
                    )
                    if isinstance(data, dict):
                        data = {**data, "LastSuccessfulUpdate": timestamp}
                    elif isinstance(data, list):
                        data = [
                            {**item, "LastSuccessfulUpdate": timestamp}
                            if isinstance(item, dict)
                            else item
                            for item in data
                        ]

                if data_point.get("name") == "Printer Events" and isinstance(data, list):
                    # The event log is newest-first on some printers, but order is
                    # not guaranteed. Publish only the highest sequence number.
                    data = max(
                        (event for event in data if isinstance(event, dict)),
                        key=lambda event: int(event.get("SequenceNumber", 0)),
                        default=None,
                    )
                if properties is not None:
                    item_filter = data_point.get("filter", {})
                    if isinstance(data, list) and item_filter:
                        data = [
                            item
                            for item in data
                            if isinstance(item, dict)
                            and all(
                                item.get(key) == expected
                                for key, expected in item_filter.items()
                            )
                        ]
                    elif isinstance(data, dict) and item_filter:
                        data = (
                            data
                            if all(
                                data.get(key) == expected
                                for key, expected in item_filter.items()
                            )
                            else None
                        )
                    if isinstance(data, list):
                        devices.extend(
                            [
                                self._get_device_data(data_item, properties, data_point)
                                for data_item in data
                            ]
                        )

                    else:
                        device = self._get_device_data(data, properties, data_point)

                        devices.append(device)

        return devices

    @staticmethod
    def _get_device_data(
        data_item: dict, properties: dict, device_config: dict
    ) -> dict:
        device_data = {}

        data_item_flat = {} if data_item is None else flatten(data_item, ".")

        for property_key in properties:
            property_details = properties.get(property_key)
            property_path = property_details.get("path")
            options = property_details.get("options")
            validation_warning = property_details.get("validationWarning", False)
            value = data_item_flat.get(property_path)
            if value is None and property_path.endswith(".#text"):
                value = data_item_flat.get(property_path[:-6])

            is_valid = True if options is None else str(value).lower() in options

            if value is not None:
                if is_valid:
                    device_data[property_key] = value
                else:
                    log = _LOGGER.warning if validation_warning else _LOGGER.debug

                    log(
                        f"Unsupported value of {property_key}, expecting: {options}, received: {value}"
                    )

        data = {"config": device_config, "data": device_data}

        return data

    async def _get_request(self, endpoint: str) -> dict | None:
        result: dict | None = None
        start_ts = datetime.now().timestamp()

        try:
            url = f"{self.config_data.url}{endpoint}"

            timeout = ClientTimeout(total=5)

            async with self._session.get(
                url, timeout=timeout, verify_ssl=False
            ) as response:
                response.raise_for_status()

                if response.content_type == "application/javascript":
                    content = await response.text()
                    result = json.loads(content)

                else:
                    content = await response.text()
                    result = self._clean_data(content)

                    if result is not None:
                        result_keys = list(result.keys())
                        root_key = result_keys[0]

                        for ignored_key in IGNORED_KEYS:
                            if ignored_key in result[root_key]:
                                del result[root_key][ignored_key]

                self._secondary_timeout_counts.pop(endpoint, None)
                completed_ts = datetime.now().timestamp()
                time_taken = completed_ts - start_ts
                _LOGGER.debug(f"Request to {url} completed, Time: {time_taken:.3f}s")

        except ClientResponseError as cre:
            if endpoint == PRODUCT_STATUS_ENDPOINT:
                self._last_status_failure = str(cre)
                return None
            if cre.status == 404:
                tb = sys.exc_info()[2]
                line_number = tb.tb_lineno
                completed_ts = datetime.now().timestamp()
                time_taken = completed_ts - start_ts

                _LOGGER.debug(
                    f"Failed to get response from {endpoint}, "
                    f"Error: {cre.status}, "
                    f"Line: {line_number}, "
                    f"Time: {time_taken:.3f}s"
                )

            else:
                tb = sys.exc_info()[2]
                line_number = tb.tb_lineno
                completed_ts = datetime.now().timestamp()
                time_taken = completed_ts - start_ts

                _LOGGER.error(
                    f"Failed to get response from {endpoint}, "
                    f"Error: {cre.status}, "
                    f"Line: {line_number}, "
                    f"Time: {time_taken:.3f}s"
                )

        except TimeoutError:
            if endpoint == PRODUCT_STATUS_ENDPOINT:
                self._last_status_failure = "request timed out"
            else:
                failures = self._secondary_timeout_counts.get(endpoint, 0) + 1
                self._secondary_timeout_counts[endpoint] = failures
                if failures == 3:
                    _LOGGER.warning(
                        "HP Printer endpoint %s timed out 3 consecutive times",
                        endpoint,
                    )
                else:
                    _LOGGER.debug("Failed to get %s due to timeout", endpoint)

        except Exception as ex:  # noqa: BLE001 - report device or API failures
            if endpoint == PRODUCT_STATUS_ENDPOINT:
                self._last_status_failure = str(ex)
            tb = sys.exc_info()[2]
            line_number = tb.tb_lineno

            completed_ts = datetime.now().timestamp()
            time_taken = completed_ts - start_ts

            if endpoint != PRODUCT_STATUS_ENDPOINT:
                _LOGGER.error(
                    f"Failed to get {endpoint}, "
                    f"Error: {ex}, "
                    f"Line: {line_number}, "
                    f"Time: {time_taken:.3f}s"
                )

        return result

    def _clean_data(self, xml) -> dict:
        xml_data = ElementTree.fromstring(xml)

        self._strip_namespace(xml_data)

        data = xmltodict.parse(ElementTree.tostring(xml_data))

        return data

    def _strip_namespace(self, el):
        if el.tag.startswith("{"):
            el.tag = el.tag.split("}", 1)[1]

        keys = list(el.attrib.keys())

        for k in keys:
            if k.startswith("{"):
                k2 = k.split("}", 1)[1]
                el.attrib[k2] = el.attrib[k]
                del el.attrib[k]

        for child in el:
            self._strip_namespace(child)

    def device_data_changed(self, device_key: str):
        device_data = self._data.get(device_key)
        device_config = self._data_config.get(device_key)

        if device_key not in self._device_dispatched:
            self._device_dispatched.append(device_key)

            dispatcher_send(
                self._hass,
                SIGNAL_HA_DEVICE_DISCOVERED,
                self._config_manager.entry_id,
                device_key,
                device_data,
                device_config,
            )
