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

## Releasing

`git tag vX.Y.Z && git push origin vX.Y.Z`. The workflow builds, verifies and
publishes.

**A published version is immutable.** The workflow refuses to touch an existing
release, and that is deliberate: package managers record the installer URL and
its SHA256, so replacing the file behind a shipped tag breaks every install of
that version. To fix a bad release, cut the next one.

### Windows Package Manager (winget)

Not submitted yet. When it is, the first submission is manual - the automation
below only handles *updates* to a package that already exists:

```powershell
winget install Microsoft.WingetCreate
wingetcreate new https://github.com/LuhOnCoffee/rgb-off/releases/download/vX.Y.Z/RGBOff-X.Y.Z-Setup.exe
```

It walks through the metadata, generates the manifest, and opens the PR against
[microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs). Validation
runs the installer in a sandbox; an unsigned installer gets extra scrutiny and
may wait on a human reviewer.

After that first version is merged, the `winget` job in the release workflow
takes over. It is already wired up and does nothing until you complete the
one-time setup:

1. Fork [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs).
2. Create a **classic** personal access token with `public_repo` scope
   (fine-grained tokens are not supported).
3. Save it as a repository secret named `WINGET_TOKEN`.
4. Pin `vedantmgoyal9/winget-releaser` to a commit SHA instead of `@v2`. It
   runs with a token that can open pull requests as you, so a tag that moves
   underneath you is a supply-chain problem.

Without the secret the job logs why it skipped and passes.

## Licence

Contributions are accepted under GPL-3.0, the licence of the project. See
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) for why it is GPL rather than
something more permissive.
