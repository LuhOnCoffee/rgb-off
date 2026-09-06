"""Mode selection is the part that silently gets hardware wrong, so it carries
the tests."""

from __future__ import annotations

import pytest

from conftest import FakeDevice, Mode, ModeColors
from rgboff import core


def test_corsair_ram_uses_custom(corsair_ram):
    """Regression: Corsair DDR4 has no Off/Static/Direct.

    Picking nothing means the RAM keeps running Rainbow Wave while we report
    success, because effect modes ignore per-LED colours.
    """
    assert core.pick_mode(corsair_ram).name == "Custom"

    core.blackout(corsair_ram, core.black())
    assert ("mode", "Custom", []) in corsair_ram.calls
    assert ("color", "#000000") in corsair_ram.calls


def test_board_uses_direct(gigabyte_board):
    assert core.pick_mode(gigabyte_board).name == "Direct"


def test_gpu_prefers_off_and_skips_colour(asus_gpu):
    assert core.pick_mode(asus_gpu).name == "Off"
    core.blackout(asus_gpu, core.black())
    kinds = [c[0] for c in asus_gpu.calls]
    assert "mode" in kinds
    # 'Off' already blanks the device; some controllers reject colours after it.
    assert "color" not in kinds


def test_colour_mode_never_picks_off(asus_gpu):
    """--color should light the device, not blank it."""
    assert core.pick_mode(asus_gpu, want_off=False).name == "Static"


def test_mode_specific_slots_are_blanked_before_switching():
    dev = FakeDevice("static only", "X",
                     [Mode("Static", ModeColors.MODE_SPECIFIC, 2),
                      Mode("Rainbow", ModeColors.NONE)])
    core.blackout(dev, core.black())
    mode_call = next(c for c in dev.calls if c[0] == "mode")
    assert mode_call[2] == ["#000000", "#000000"]


def test_unknown_mode_names_fall_back_to_per_led_flag():
    dev = FakeDevice("vendor thing", "X",
                     [Mode("Vendor Effect A", ModeColors.NONE),
                      Mode("Live Feed", ModeColors.PER_LED)])
    assert core.pick_mode(dev).name == "Live Feed"


def test_device_with_no_modes_still_gets_colours():
    dev = FakeDevice("no modes", "X", [])
    detail = core.blackout(dev, core.black())
    assert "colours only" in detail
    assert ("color", "#000000") in dev.calls


def test_set_mode_by_name_fallback():
    dev = FakeDevice("name only", "X", [Mode("Direct", ModeColors.PER_LED)],
                     mode_by_name_only=True)
    detail = core.blackout(dev, core.black())
    assert "mode=Direct" in detail
    assert ("mode_by_name", "Direct") in dev.calls


def test_mode_failure_still_sets_colours():
    dev = FakeDevice("stubborn", "X", [Mode("Direct", ModeColors.PER_LED)],
                     mode_always_fails=True)
    detail = core.blackout(dev, core.black())
    assert "mode failed" in detail
    assert ("color", "#000000") in dev.calls


def test_save_mode_recorded_when_supported():
    dev = FakeDevice("saver", "X", [Mode("Direct", ModeColors.PER_LED)],
                     supports_save=True)
    assert "saved to device" in core.blackout(dev, core.black())


def test_apply_all_isolates_failures(corsair_ram):
    class Exploding(FakeDevice):
        def set_color(self, color):
            raise RuntimeError("boom")

        def set_mode(self, mode):
            raise RuntimeError("boom")

    bad = Exploding("bad", "X", [])
    results = core.apply_all([corsair_ram, bad], core.black())
    assert results[0].ok
    # One stubborn device must never abort the run.
    assert len(results) == 2


@pytest.mark.parametrize("text,expected", [
    ("000000", (0, 0, 0)),
    ("#20AaFF", (32, 170, 255)),
    ("ffffff", (255, 255, 255)),
])
def test_parse_color(text, expected):
    c = core.parse_color(text)
    assert (c.red, c.green, c.blue) == expected


@pytest.mark.parametrize("text", ["", "12345", "gggggg", "#1234567"])
def test_parse_color_rejects_junk(text):
    with pytest.raises(ValueError):
        core.parse_color(text)


def test_summarize(corsair_ram):
    assert core.summarize([]) == "No devices detected."
    results = core.apply_all([corsair_ram], core.black())
    assert "All 1 devices dark" in core.summarize(results)


@pytest.mark.parametrize("raw,expected", [
    ("MOTHERBOARD", "Motherboard"),
    ("DRAM", "DRAM"),
    ("GPU", "GPU"),
    ("MOUSE", "Mouse"),
    ("LEDSTRIP", "LED strip"),
    ("HEADSET_STAND", "Headset stand"),
    ("SOME_FUTURE_TYPE", "Some Future Type"),
    ("", "Unknown"),
    (None, "Unknown"),
])
def test_pretty_device_type(raw, expected):
    """OpenRGB shouts its enum names; the UI should not."""
    assert core.pretty_device_type(raw) == expected


def test_device_type_of_reads_the_device(asus_gpu):
    assert core.device_type_of(asus_gpu) == "GPU"


def test_results_carry_the_pretty_type(corsair_ram):
    results = core.apply_all([corsair_ram], core.black())
    assert results[0].kind == "DRAM"


# --------------------------------------------------------------------------- #
# device-list settling
# --------------------------------------------------------------------------- #

class GrowingClient:
    """OpenRGB answers its SDK port before it has finished enumerating.

    A client that connects the instant the port opens sees only the devices
    detected so far - in practice the SMBus ones, since those come first.
    """

    def __init__(self, stages):
        self._stages = list(stages)
        self.reloads = 0
        self.devices = self._stages[0]

    def update(self):
        self.reloads += 1
        if self._stages:
            self._stages.pop(0)
        if self._stages:
            self.devices = self._stages[0]


def test_wait_for_devices_waits_out_a_growing_list():
    """The bug: two RAM sticks on launch, five devices after a manual refresh."""
    ram, board, gpu = ["ram1", "ram2"], ["ram1", "ram2", "board"], list("abcde")
    client = GrowingClient([ram, board, gpu, gpu])
    assert core.wait_for_devices(client, interval=0) == 5


def test_wait_for_devices_returns_immediately_when_already_stable():
    client = GrowingClient([list("abc"), list("abc")])
    assert core.wait_for_devices(client, interval=0) == 3


def test_wait_for_devices_gives_up_rather_than_hanging():
    forever = GrowingClient([[1], [1, 2], [1, 2, 3], [1, 2, 3, 4]])
    forever._stages = [[1], [1, 2], [1, 2, 3], [1, 2, 3, 4]] * 10
    assert core.wait_for_devices(forever, tries=4, interval=0) >= 1
    assert forever.reloads <= 4


def test_wait_for_devices_stops_when_the_client_cannot_reload():
    class NoReload:
        devices = ["only-one"]

    assert core.wait_for_devices(NoReload(), interval=0) == 1


def test_reload_devices_reports_whether_it_worked():
    class Fine:
        def update(self):
            pass

    class Broken:
        def update(self):
            raise RuntimeError("no")

    class Nothing:
        pass

    assert core.reload_devices(Fine()) is True
    assert core.reload_devices(Broken()) is False
    assert core.reload_devices(Nothing()) is False
