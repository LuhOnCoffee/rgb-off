"""Finding OpenRGB, making sure its SDK server is up, and checking PawnIO.

Windows-specific. Everything degrades to "not found" on other platforms so the
module can still be imported for tests.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from .core import HOST, PORT

IS_WINDOWS = sys.platform == "win32"

# Package ids. OpenRGB moved from CalcProgrammer1.OpenRGB to OpenRGB.OpenRGB;
# the old id no longer resolves, so try the current one first.
WINGET_OPENRGB = ("OpenRGB.OpenRGB", "CalcProgrammer1.OpenRGB")
WINGET_PAWNIO = ("namazso.PawnIO",)

PAWNIO_URL = "https://pawnio.eu"
OPENRGB_URL = "https://openrgb.org"

_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW


def _run(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout,
        creationflags=_NO_WINDOW,
    )


# --------------------------------------------------------------------------- #
# locating OpenRGB
# --------------------------------------------------------------------------- #

def _reg_str(key, name: str, default: str = "") -> str:
    """Read one string value. Module level so it never closes over a loop var."""
    import winreg  # noqa: PLC0415

    try:
        return str(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return default


def _registry_candidates() -> list[Path]:
    """InstallLocation / DisplayIcon from uninstall keys mentioning OpenRGB."""
    if not IS_WINDOWS:
        return []
    import winreg  # noqa: PLC0415

    out: list[Path] = []
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                except OSError:
                    continue
                with sub:
                    if "openrgb" not in _reg_str(sub, "DisplayName").lower():
                        continue
                    loc = _reg_str(sub, "InstallLocation")
                    if loc:
                        out.append(Path(loc) / "OpenRGB.exe")
                    icon = _reg_str(sub, "DisplayIcon")
                    if icon:
                        out.append(Path(icon.split(",")[0].strip('"')))
    return out


def find_openrgb(extra_dirs: list[Path] | None = None) -> Path | None:
    """Full path to OpenRGB.exe, or None."""
    if not IS_WINDOWS:
        return None

    candidates: list[Path] = []
    for d in (extra_dirs or []):
        candidates.append(Path(d) / "OpenRGB.exe")

    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    lad = os.environ.get("LOCALAPPDATA", "")
    pd = os.environ.get("ProgramData", "")
    candidates += [
        Path(pf) / "OpenRGB" / "OpenRGB.exe",
        Path(pf86) / "OpenRGB" / "OpenRGB.exe",
        Path(lad) / "Programs" / "OpenRGB" / "OpenRGB.exe" if lad else Path(),
        Path(lad) / "OpenRGB" / "OpenRGB.exe" if lad else Path(),
        Path(pd) / "OpenRGB" / "OpenRGB.exe" if pd else Path(),
        Path(r"C:\OpenRGB\OpenRGB.exe"),
    ]
    candidates += _registry_candidates()

    # winget portable packages
    if lad:
        store = Path(lad) / "Microsoft" / "WinGet" / "Packages"
        if store.is_dir():
            candidates += list(store.glob("*/**/OpenRGB.exe"))

    for c in candidates:
        try:
            if c and c.is_file():
                return c
        except OSError:
            continue
    return None


# --------------------------------------------------------------------------- #
# the SDK server
# --------------------------------------------------------------------------- #

def server_is_up(host: str = HOST, port: int = PORT, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def start_server(openrgb: Path, wait_seconds: int = 25) -> bool:
    """Launch OpenRGB in server mode and wait for the port to answer."""
    if server_is_up():
        return True
    try:
        subprocess.Popen(
            [str(openrgb), "--server", "--startminimized"],
            creationflags=_NO_WINDOW,
        )
    except OSError:
        return False

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if server_is_up():
            return True
        time.sleep(1)
    return False


def ensure_server(extra_dirs: list[Path] | None = None) -> tuple[bool, str]:
    """(ok, message). Finds OpenRGB and gets the SDK server listening."""
    if server_is_up():
        return True, "OpenRGB SDK server is running."

    exe = find_openrgb(extra_dirs)
    if exe is None:
        return False, ("OpenRGB is not installed. Use Setup to install it, "
                       f"or get it from {OPENRGB_URL}.")

    if start_server(exe):
        return True, f"Started the OpenRGB SDK server ({exe})."
    return False, (f"Started {exe} but nothing is listening on {PORT}. "
                   "Check Settings > General > Start Server in OpenRGB.")


# --------------------------------------------------------------------------- #
# winget helpers
# --------------------------------------------------------------------------- #

def has_winget() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return _run(["winget", "--version"], timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def winget_install(package_ids: tuple[str, ...], check) -> tuple[bool, str]:
    """Try each id in turn until `check()` says the thing is present."""
    if check():
        return True, "already installed"
    if not has_winget():
        return False, "winget is not available on this PC"

    tried: list[str] = []
    for pid in package_ids:
        tried.append(pid)
        try:
            _run(["winget", "install", "--id", pid, "--exact",
                  "--accept-package-agreements", "--accept-source-agreements"])
        except (OSError, subprocess.SubprocessError) as err:
            return False, f"winget failed: {err}"
        if check():
            return True, f"installed via winget ({pid})"
    return False, f"winget could not install any of: {', '.join(tried)}"


# --------------------------------------------------------------------------- #
# PawnIO
# --------------------------------------------------------------------------- #

def pawnio_installed() -> bool:
    """
    Modern OpenRGB reaches the SMBus through PawnIO instead of the old WinRing0.
    Without it you get 'PawnIO module initialization aborted' and RAM, GPU and
    most motherboard controllers never appear at all.
    """
    if not IS_WINDOWS:
        return False

    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    if (Path(pf) / "PawnIO").is_dir():
        return True

    import winreg  # noqa: PLC0415
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Services\PawnIO"):
            return True
    except OSError:
        pass

    for hive, path in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ):
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                except OSError:
                    continue
                with sub:
                    if "pawnio" in _reg_str(sub, "DisplayName").lower():
                        return True
    return False


def install_pawnio() -> tuple[bool, str]:
    return winget_install(WINGET_PAWNIO, pawnio_installed)


def install_openrgb() -> tuple[bool, str]:
    return winget_install(WINGET_OPENRGB, lambda: find_openrgb() is not None)


# --------------------------------------------------------------------------- #
# OpenRGB settings
# --------------------------------------------------------------------------- #

def enable_sdk_server_in_settings() -> tuple[bool, str]:
    """Set Server host/port in OpenRGB.json so the GUI starts the server too."""
    import json  # noqa: PLC0415

    appdata = os.environ.get("APPDATA")
    if not appdata:
        return False, "APPDATA is not set"

    cfg_dir = Path(appdata) / "OpenRGB"
    cfg = cfg_dir / "OpenRGB.json"
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if cfg.is_file():
            raw = cfg.read_text(encoding="utf-8").strip()
            if raw:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    data = loaded
        data["Server"] = {"host": HOST, "port": PORT}
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True, f"SDK server enabled in {cfg}"
    except (OSError, ValueError) as err:
        return False, f"could not update OpenRGB.json: {err}"
