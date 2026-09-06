"""A fake `openrgb` module so the device logic can be tested anywhere.

rgboff.core imports openrgb lazily inside functions precisely so this works -
the real library only exists on a machine that has OpenRGB.
"""

from __future__ import annotations

import sys
import types
from enum import Enum

import pytest


class RGBColor:
    def __init__(self, red: int, green: int, blue: int):
        self.red, self.green, self.blue = red, green, blue

    def __eq__(self, other):
        return (self.red, self.green, self.blue) == (other.red, other.green, other.blue)

    def __repr__(self):
        return f"#{self.red:02X}{self.green:02X}{self.blue:02X}"


class ModeColors(Enum):
    NONE = 0
    PER_LED = 1
    MODE_SPECIFIC = 2
    RANDOM = 3


def _install_fake_openrgb() -> None:
    pkg = types.ModuleType("openrgb")
    utils = types.ModuleType("openrgb.utils")
    utils.RGBColor = RGBColor
    utils.ModeColors = ModeColors

    class OpenRGBClient:                      # pragma: no cover - not exercised
        def __init__(self, *args, **kwargs):
            self.devices = []

        def disconnect(self):
            pass

    pkg.OpenRGBClient = OpenRGBClient
    pkg.utils = utils
    sys.modules.setdefault("openrgb", pkg)
    sys.modules.setdefault("openrgb.utils", utils)


_install_fake_openrgb()


# --------------------------------------------------------------------------- #
# fake devices
# --------------------------------------------------------------------------- #

class Mode:
    def __init__(self, name: str, color_mode: ModeColors = ModeColors.NONE,
                 slots: int = 0):
        self.name = name
        self.color_mode = color_mode
        self.colors = [RGBColor(255, 0, 0) for _ in range(slots)]


class DeviceType:
    def __init__(self, name: str):
        self.name = name


class FakeDevice:
    """Records what was done to it, and can be told which calls should fail."""

    def __init__(self, name: str, kind: str, modes: list[Mode], leds: int = 4, *,
                 mode_by_name_only: bool = False, mode_always_fails: bool = False,
                 supports_save: bool = False):
        self.name = name
        self.type = DeviceType(kind)
        self.modes = modes
        self.leds = [0] * leds
        self.calls: list[tuple] = []
        self._by_name_only = mode_by_name_only
        self._mode_fails = mode_always_fails
        self._supports_save = supports_save

    def set_mode(self, mode):
        if self._mode_fails:
            raise RuntimeError("controller refused")
        if self._by_name_only:
            if not isinstance(mode, str):
                raise TypeError("object form unsupported")
            self.calls.append(("mode_by_name", mode))
            return
        if isinstance(mode, str):
            raise TypeError("name form unsupported")
        self.calls.append(("mode", mode.name, [repr(c) for c in mode.colors]))

    def set_color(self, color):
        self.calls.append(("color", repr(color)))

    def save_mode(self):
        if not self._supports_save:
            raise NotImplementedError
        self.calls.append(("save",))


@pytest.fixture
def corsair_ram() -> FakeDevice:
    """No Off, no Static, no Direct - only 'Custom'. The case that bit us."""
    modes = [Mode("Custom", ModeColors.PER_LED)] + [
        Mode(n, ModeColors.MODE_SPECIFIC, 1)
        for n in ("Color Shift", "Color Pulse", "Rainbow Wave", "Color Wave",
                  "Visor", "Rain", "Marquee", "Rainbow", "Sequential")
    ]
    return FakeDevice("Corsair Vengeance RGB Pro DDR4", "DRAM", modes, 10)


@pytest.fixture
def gigabyte_board() -> FakeDevice:
    modes = [Mode("Direct", ModeColors.PER_LED)] + [
        Mode(n, ModeColors.MODE_SPECIFIC, 1)
        for n in ("Pulse", "Flashing", "Color Cycle", "Digital Wave", "Digital A")
    ]
    return FakeDevice("X470 AORUS GAMING 7 WIFI-CF", "MOTHERBOARD", modes, 10)


@pytest.fixture
def asus_gpu() -> FakeDevice:
    modes = [
        Mode("Direct", ModeColors.PER_LED),
        Mode("Off", ModeColors.NONE),
        Mode("Static", ModeColors.MODE_SPECIFIC, 1),
        Mode("Breathing", ModeColors.MODE_SPECIFIC, 1),
        Mode("Spectrum Cycle", ModeColors.NONE),
    ]
    return FakeDevice("ASUS ROG STRIX RTX 2080 Ti", "GPU", modes, 1)
