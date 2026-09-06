"""Administrator checks.

PawnIO only grants SMBus access to an elevated process, and SMBus is how RAM,
GPU and most motherboard controllers are reached. Without admin the app runs
fine and simply never sees those devices, which looks like a detection bug -
so the UI says so plainly instead.
"""

from __future__ import annotations

import ctypes
import sys

IS_WINDOWS = sys.platform == "win32"


def is_admin() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(extra_args: list[str] | None = None) -> bool:
    """Re-launch this process elevated. True if the UAC prompt was accepted."""
    if not IS_WINDOWS or is_admin():
        return False

    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = sys.argv[1:]
    else:
        exe = sys.executable
        args = ["-m", "rgboff", *sys.argv[1:]]
    args = args + (extra_args or [])

    params = " ".join(f'"{a}"' for a in args)
    try:
        # >32 means success; anything else is a declined or failed elevation.
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return rc > 32
    except Exception:
        return False
