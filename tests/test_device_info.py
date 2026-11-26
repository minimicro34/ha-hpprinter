"""Ensure entity names work with both DeviceInfo representations."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from custom_components.hpprinter.managers.ha_config_manager import HAConfigManager


@dataclass
class ModernDeviceInfo:
    name: str

    def get(self, key):
        raise AssertionError("Deprecated mapping access must not be used")


@pytest.mark.parametrize("device_info", [ModernDeviceInfo("Printer"), {"name": "Printer"}])
def test_entity_name_device_info_compatibility(device_info):
    manager = HAConfigManager(None, None)
    manager._translations = {}
    description = SimpleNamespace(translation_key="count", platform="sensor", name="Count")
    assert manager.get_entity_name(description, device_info) == "Printer Count"
