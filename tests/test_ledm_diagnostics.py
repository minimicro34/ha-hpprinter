"""Regression tests for the HP ENVY LEDM diagnostic endpoints."""

import json
from pathlib import Path
from unittest.mock import Mock

from custom_components.hpprinter.managers.rest_api import RestAPIv2


def test_new_ledm_data_points_have_unique_names_and_diagnostic_category():
    path = (
        Path(__file__).resolve().parents[1]
        / "custom_components/hpprinter/parameters/data_points.json"
    )
    points = json.loads(path.read_text(encoding="utf-8"))
    for name in (
        "WiFi Statistics",
        "Printer Settings",
        "Printer Memory",
        "Paper Tray",
        "Printer Events",
    ):
        matches = [point for point in points if point["name"] == name]
        assert len(matches) == 1
        assert all(
            prop["entity_category"] == "diagnostic"
            for prop in matches[0]["properties"].values()
        )


def test_latest_event_uses_highest_sequence_number():
    manager = Mock()
    manager.endpoints = ["/DevMgmt/ProductLogsDyn.xml"]
    manager.entry_id = "test"
    manager.data_points = [
        {
            "name": "Printer Events",
            "endpoint": "/DevMgmt/ProductLogsDyn.xml",
            "path": "ProductLogsDyn.EventLog.Event",
            "device_type": "Main",
            "properties": {
                "event_code": {"path": "EventCode", "platform": "sensor"},
                "event_sequence": {"path": "SequenceNumber", "platform": "sensor"},
            },
        }
    ]
    api = RestAPIv2(None, manager)
    api._raw_data["/DevMgmt/ProductLogsDyn.xml"] = {
        "ProductLogsDyn": {
            "EventLog": {
                "Event": [
                    {"SequenceNumber": "1724", "EventCode": "old"},
                    {"SequenceNumber": "1734", "EventCode": "74740"},
                ]
            }
        }
    }
    devices = api._get_devices_data()
    assert len(devices) == 1
    assert devices[0]["data"]["event_code"] == "74740"
    assert devices[0]["data"]["event_sequence"] == "1734"
