"""Regression tests for extraction and discovery of printer entities."""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from custom_components.hpprinter.managers.rest_api import RestAPIv2


@pytest.fixture
def api():
    manager = Mock()
    manager.endpoints = []
    manager.entry_id = "test"
    return RestAPIv2(None, manager)


def item(device_type, data, **config):
    return {
        "config": {
            "device_type": device_type,
            "properties": {key: {"path": key} for key in data},
            **config,
        },
        "data": data,
    }


def test_merge_and_discover_devices_once(api):
    devices = [
        item("Main", {"status": "ready"}),
        item("Main", {"count": "42"}),
        item("Consumable", {"color": "K", "level": "80"},
             identifier={"key": "color"}),
        item("Empty", {}),
    ]
    with patch("custom_components.hpprinter.managers.rest_api.dispatcher_send") as send:
        api._extract_data(devices)
        assert api.data == {
            "Main": {"status": "ready", "count": "42"},
            "Consumable.K": {"color": "K", "level": "80"},
        }
        assert set(api.data_config["Main"]["properties"]) == {"status", "count"}
        assert send.call_count == 2
        assert {call.args[3] for call in send.call_args_list} == {"Main", "Consumable.K"}
        api._extract_data([item("Main", {"count": "43"})])
        assert api.data["Main"]["count"] == "43"
        assert send.call_count == 2


def test_flat_identifiers_use_mapped_names(api):
    devices = [
        item("Printer", {"media": "A", "count": "12"},
             identifier={"key": "media", "mapping": {"A": "Plain Paper"}}, flat=True),
        item("Printer", {"media": "B", "count": "5"},
             identifier={"key": "media", "mapping": {"B": "Photo Paper"}}, flat=True),
    ]
    with patch("custom_components.hpprinter.managers.rest_api.dispatcher_send"):
        api._extract_data(devices)
    assert api.data == {"Printer": {"plain_paper_count": "12", "photo_paper_count": "5"}}
    assert set(api.data_config["Printer"]["properties"]) == {
        "plain_paper_count", "photo_paper_count"
    }


def test_recursive_media_usage(api):
    api._config_manager.data_points = [{
        "name": "Media", "endpoint": "/usage", "recursive_media_type": True,
        "device_type": "Printer", "properties": {"count": {"path": "Count"}},
    }]
    api._raw_data["/usage"] = {"Root": [
        {"UsageByMediaType": {"Count": "12"}},
        {"Nested": {"UsageByMediaType": [{"Count": "5"}, "invalid"]}},
    ]}
    assert [entry["data"] for entry in api._get_devices_data()] == [
        {"count": "12"}, {"count": "5"}
    ]


@pytest.mark.parametrize("payload", [{"Status": "off"}, [{"Status": "off"}]])
def test_cached_timestamp_is_exposed_without_mutating_payload(api, payload):
    api._last_successful_update = 1234
    api._config_manager.data_points = [{
        "name": "Status", "endpoint": "/status", "path": "Root",
        "device_type": "Main",
        "properties": {"updated": {"path": "LastSuccessfulUpdate"}},
    }]
    api._raw_data["/status"] = {"Root": payload}
    data = api._get_devices_data()[0]["data"]
    assert datetime.fromisoformat(data["updated"]).timestamp() == 1234
    assert api._raw_data["/status"]["Root"] == payload
    for entry in payload if isinstance(payload, list) else [payload]:
        assert "LastSuccessfulUpdate" not in entry


@pytest.mark.parametrize("adapter, expected", [
    ("Wifi0", {"channel": "11"}), ("Wifi1", {}),
])
def test_single_adapter_filter(api, adapter, expected):
    api._config_manager.data_points = [{
        "name": "WiFi Radio", "endpoint": "/wifi", "path": "Adapter",
        "device_type": "Main", "filter": {"Name": "Wifi0"},
        "properties": {"channel": {"path": "Channel"}},
    }]
    api._raw_data["/wifi"] = {"Adapter": {"Name": adapter, "Channel": "11"}}
    assert api._get_devices_data()[0]["data"] == expected


def test_scalar_text_and_invalid_options(caplog):
    properties = {
        "count": {"path": "Count.#text"},
        "status": {"path": "Status", "options": ["ready"]},
        "mode": {"path": "Mode", "options": ["on"], "validationWarning": True},
    }
    result = RestAPIv2._get_device_data(
        {"Count": "42", "Status": "READY", "Mode": "invalid"}, properties, {}
    )
    assert result["data"] == {"count": "42", "status": "READY"}
    assert "Unsupported value of mode" in caplog.text


def test_ambiguous_wifi_fallback_does_not_select_arbitrary_signal():
    result = RestAPIv2._get_device_data(
        {"First": {"dBm": "-40"}, "Second": {"dBm": "-80"}},
        {"signal": {"path": "Expected.dBm"}},
        {"name": "WiFi Radio"},
    )
    assert result["data"] == {}
