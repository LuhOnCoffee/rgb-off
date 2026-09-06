# Contributing

Bug reports are more useful here than pull requests, because the failure modes
are almost always hardware-specific and I can only test on one machine.

## Reporting a device that stays lit

This is the most valuable report. Include the output of:

```
rgboff-cli --list
```

It shows every device OpenRGB detected, the modes each one exposes, and which
mode RGB Off would pick. That last line is usually where the answer is — a
controller whose only usable mode has a vendor-specific name the picker doesn't
recognise. [`NAME_PREFERENCE_OFF`](src/rgboff/core.py) is where such a name gets
added, and there is a test for the case that motivated it (Corsair DDR4 exposes
no `Off`, `Static` or `Direct` — only `Custom`).

Also say whether the device stays lit immediately, comes back after a few
seconds (a controller watchdog — try the hold option), or comes back after a
reboot (expected on hardware that can't store an off state).

## Adding vendor software to the catalogue

[`src/rgboff/vendors.py`](src/rgboff/vendors.py) holds the catalogue. A new entry
needs the display name patterns as they appear in the Windows uninstall
registry, and an honest `cooling` flag — `True` for anything that also controls
fan curves, pump speed, DPI or macro profiles, so it is unticked by default and
the user is told what they'd lose.

## Development

```bash
git clone https://github.com/LuhOnCoffee/rgb-off
cd rgb-off
pip install -e ".[gui,dev]"
pytest          # no hardware and no OpenRGB install needed
ruff check src tests packaging
python -m rgboff
```

The tests run against a fake `openrgb` module in
[`tests/conftest.py`](tests/conftest.py). `core.py` imports `openrgb` lazily
inside functions specifically so this works — please keep it that way, since it
is what lets mode selection be verified on any OS.

CI runs `ruff` and `pytest` on every push. The release workflow additionally
checks the PE subsystem of each built executable, because a case-insensitive
filename collision once shipped the console build as the GUI one.

## Licence

Contributions are accepted under GPL-3.0, the licence of the project. See
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) for why it is GPL rather than
something more permissive.
