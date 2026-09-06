"""Device logic: connect to OpenRGB, choose a mode per device, blank it.

This module is deliberately free of GUI and Windows-specific code so the mode
selection can be tested on any platform with a stub client.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

HOST = "127.0.0.1"
PORT = 6742
CLIENT_NAME = "rgboff"
CONNECT_RETRIES = 10
CONNECT_RETRY_DELAY = 1.0
REFRESH_SECONDS = 5

# Name preference, best first.
#   Off     - the controller's own blackout. Stored on the device, often
#             survives a reboot.
#   Static  - colour stored on the controller, so it sticks after we exit.
#   Direct  - host drives the LEDs live.
#   Custom  - what Corsair (and some others) call their per-LED mode. Corsair
#             Vengeance RGB Pro exposes no Off/Static/Direct at all, so without
#             this entry it would sit on Rainbow Wave while we reported success.
NAME_PREFERENCE_OFF = ("off", "static", "direct", "custom")
NAME_PREFERENCE_COLOR = ("static", "direct", "custom")


class OpenRGBUnavailable(RuntimeError):
    """The SDK server could not be reached."""


@dataclass(frozen=True)
class DeviceResult:
    name: str
    kind: str
    ok: bool
    detail: str


# --------------------------------------------------------------------------- #
# imports that only exist on a machine with the client library installed
# --------------------------------------------------------------------------- #

def _rgb_types():
    from openrgb.utils import RGBColor  # noqa: PLC0415

    try:
        from openrgb.utils import ModeColors  # noqa: PLC0415
    except ImportError:                      # pragma: no cover - old builds
        ModeColors = None
    return RGBColor, ModeColors


def black():
    RGBColor, _ = _rgb_types()
    return RGBColor(0, 0, 0)


def parse_color(text: str):
    """Accept RRGGBB or #RRGGBB. Raises ValueError on anything else."""
    RGBColor, _ = _rgb_types()
    cleaned = text.strip().lstrip("#")
    if len(cleaned) != 6:
        raise ValueError("colour must be 6 hex digits, e.g. 202020")
    r, g, b = (int(cleaned[i:i + 2], 16) for i in (0, 2, 4))
    return RGBColor(r, g, b)


# --------------------------------------------------------------------------- #
# connection
# --------------------------------------------------------------------------- #

def connect(host: str = HOST, port: int = PORT, retries: int = CONNECT_RETRIES,
            delay: float = CONNECT_RETRY_DELAY, on_wait=None):
    """Connect to the OpenRGB SDK server, retrying while it starts up."""
    from openrgb import OpenRGBClient  # noqa: PLC0415

    last_err: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return OpenRGBClient(host, port, CLIENT_NAME)
        except Exception as err:              # ConnectionRefused, timeout, ...
            last_err = err
            if attempt == 1 and on_wait:
                on_wait(f"Waiting for the OpenRGB SDK server on {host}:{port} ...")
            if attempt < retries:
                time.sleep(delay)
    raise OpenRGBUnavailable(
        f"Could not reach the OpenRGB SDK server at {host}:{port} ({last_err})."
    )


# --------------------------------------------------------------------------- #
# mode selection
# --------------------------------------------------------------------------- #

def color_mode_of(mode: Any) -> str:
    """
    'per_led'       - host sets each LED individually (Direct, Custom, ...)
    'mode_specific' - the mode carries its own colour slots (Static on many
                      controllers); blanking means zeroing mode.colors first.
    'none'          - the mode ignores colour entirely (Off, Rainbow, ...)
    'unknown'       - this build of openrgb-python doesn't say.
    """
    _, ModeColors = _rgb_types()
    if ModeColors is None:
        return "unknown"
    cm = getattr(mode, "color_mode", None)
    if cm is None:
        return "unknown"
    try:
        if cm == ModeColors.PER_LED:
            return "per_led"
        if cm == ModeColors.MODE_SPECIFIC:
            return "mode_specific"
        return "none"
    except Exception:                          # pragma: no cover
        return "unknown"


def pick_mode(device: Any, want_off: bool = True):
    """Return the mode object to switch to, or None if nothing fits."""
    modes = list(getattr(device, "modes", []) or [])
    if not modes:
        return None

    by_name: dict[str, Any] = {}
    for m in modes:
        n = getattr(m, "name", None)
        if n:
            by_name.setdefault(n.strip().lower(), m)

    for candidate in (NAME_PREFERENCE_OFF if want_off else NAME_PREFERENCE_COLOR):
        if candidate in by_name:
            return by_name[candidate]

    # No familiar name. Take any mode the controller flags as host-driven.
    # This is what rescues devices with vendor-specific mode names.
    for m in modes:
        if color_mode_of(m) == "per_led":
            return m
    for m in modes:
        if color_mode_of(m) == "mode_specific":
            return m
    return None


#: OpenRGB reports device types as SHOUTING enum names. Acronyms stay
#: uppercase; everything else reads as a normal noun.
DEVICE_TYPE_NAMES = {
    "MOTHERBOARD": "Motherboard",
    "DRAM": "DRAM",
    "GPU": "GPU",
    "COOLER": "Cooler",
    "LEDSTRIP": "LED strip",
    "KEYBOARD": "Keyboard",
    "MOUSE": "Mouse",
    "MOUSEMAT": "Mousemat",
    "HEADSET": "Headset",
    "HEADSET_STAND": "Headset stand",
    "GAMEPAD": "Gamepad",
    "LIGHT": "Light",
    "SPEAKER": "Speaker",
    "VIRTUAL": "Virtual",
    "STORAGE": "Storage",
    "CASE": "Case",
    "MICROPHONE": "Microphone",
    "ACCESSORY": "Accessory",
    "KEYPAD": "Keypad",
    "LAPTOP": "Laptop",
    "MONITOR": "Monitor",
    "UNKNOWN": "Unknown",
}


#: Kept uppercase when a type OpenRGB adds later isn't in the table above.
TYPE_ACRONYMS = frozenset({"DRAM", "GPU", "CPU", "LED", "RGB", "SSD", "HDD",
                           "USB", "PSU", "AIO", "PC"})


def pretty_device_type(name: str | None) -> str:
    """MOTHERBOARD -> Motherboard, DRAM -> DRAM, HEADSET_STAND -> Headset stand."""
    if not name:
        return "Unknown"
    key = name.strip().upper()
    if key in DEVICE_TYPE_NAMES:
        return DEVICE_TYPE_NAMES[key]
    words = key.replace("_", " ").split()
    return " ".join(w if w in TYPE_ACRONYMS else w.capitalize()
                    for w in words) or "Unknown"


def device_type_of(device: Any) -> str:
    return pretty_device_type(getattr(getattr(device, "type", None), "name", None))


def describe_plan(device: Any, want_off: bool = True) -> str:
    mode = pick_mode(device, want_off)
    name = getattr(mode, "name", None)
    return name or "no usable mode - colours only"


# --------------------------------------------------------------------------- #
# applying
# --------------------------------------------------------------------------- #

def blackout(device: Any, color: Any, want_off: bool = True) -> str:
    """Blank one device. Returns a short human-readable status."""
    RGBColor, _ = _rgb_types()
    notes: list[str] = []

    mode = pick_mode(device, want_off)
    mode_name = (getattr(mode, "name", "") or "").strip() if mode is not None else ""

    if mode is not None:
        # A mode carrying its own colour slots must be blanked before the
        # switch, or it comes up in whatever colour it remembered.
        if color_mode_of(mode) == "mode_specific":
            try:
                slots = list(getattr(mode, "colors", []) or [])
                if slots:
                    mode.colors = [RGBColor(color.red, color.green, color.blue)
                                   for _ in slots]
            except Exception:
                pass

        applied = False
        try:
            device.set_mode(mode)
            applied = True
        except Exception:
            # Some builds accept only the name, others only the object.
            try:
                device.set_mode(mode_name)
                applied = True
            except Exception as err:
                notes.append(f"mode failed ({type(err).__name__})")
                mode = None
        if applied:
            notes.append(f"mode={mode_name}")

    if mode is None and not notes:
        notes.append("no usable mode - colours only")

    # 'Off' already blanks the device; pushing colours at it is pointless and a
    # few controllers reject it outright.
    if mode_name.lower() != "off":
        try:
            device.set_color(color)
            notes.append("colour set")
        except Exception as err:
            notes.append(f"colour failed ({type(err).__name__})")

    # Persist to the controller's own flash where firmware supports it.
    try:
        device.save_mode()
        notes.append("saved to device")
    except Exception:
        pass

    return ", ".join(notes) or "nothing to do"


def apply_all(devices: Iterable[Any], color: Any,
              want_off: bool = True) -> list[DeviceResult]:
    results: list[DeviceResult] = []
    for dev in devices:
        kind = device_type_of(dev)
        try:
            results.append(DeviceResult(dev.name, kind, True,
                                        blackout(dev, color, want_off)))
        except Exception as err:
            results.append(DeviceResult(dev.name, kind, False,
                                        f"{type(err).__name__}: {err}"))
    return results


def turn_off(client: Any = None, color: Any = None,
             want_off: bool = True) -> list[DeviceResult]:
    """Convenience: connect if needed, blank everything, return per-device rows."""
    owned = client is None
    if owned:
        client = connect()
    if color is None:
        color = black()
    try:
        return apply_all(client.devices, color, want_off)
    finally:
        if owned:
            try:
                client.disconnect()
            except Exception:
                pass


def summarize(results: Sequence[DeviceResult]) -> str:
    failed = [r for r in results if not r.ok]
    if not results:
        return "No devices detected."
    if failed:
        return f"{len(results) - len(failed)} of {len(results)} devices dark; " \
               f"{len(failed)} refused."
    return f"All {len(results)} devices dark."
