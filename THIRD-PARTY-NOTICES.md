# Third-party notices

RGB Off is distributed under the GNU General Public License v3.0. That choice is
not arbitrary — it follows from what the released binaries contain.

## Bundled into the released executables

The PyInstaller builds (`RGBOff.exe`, `rgboff-cli.exe`) embed these libraries,
which makes each executable a combined work:

| Component | Licence | Role |
|---|---|---|
| [openrgb-python](https://github.com/jath03/openrgb-python) | **GPL-3.0** | Client for the OpenRGB SDK protocol |
| [CPython](https://www.python.org/) and Tcl/Tk | PSF / BSD-style | Runtime and GUI toolkit |
| [PyInstaller](https://pyinstaller.org/) bootloader | GPL-2.0 with an exception permitting bundling under any licence | Packaging |

`openrgb-python` is GPL-3.0 and is imported directly by this application, so the
combined executable is licensed as a whole under GPL-3.0. Source for this
project is at <https://github.com/LuhOnCoffee/rgb-off>; source for each library
is at the links above.

## Used, but not bundled

These are separate programs the user installs. RGB Off communicates with them at
arm's length and does not incorporate their code:

| Component | Licence | How it is used |
|---|---|---|
| [OpenRGB](https://openrgb.org) | GPL-2.0 | A separate process, reached over its SDK socket on `127.0.0.1:6742` |
| [PawnIO](https://pawnio.eu) | See the project's own terms | A driver OpenRGB uses for SMBus access |

Installing them is optional and under the user's control; RGB Off offers to
fetch them through `winget` for convenience.

## Not affiliated

This project is not affiliated with or endorsed by OpenRGB, PawnIO, or any
hardware vendor named in its device catalogue. Product names are used only to
identify the software they refer to.
