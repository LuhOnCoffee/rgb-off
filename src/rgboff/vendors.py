"""Finding and removing vendor RGB software.

Vendor apps hold the lighting controllers open and re-paint them continuously,
so OpenRGB and (say) iCUE cannot share the hardware. This module locates what
is installed and removes it through each vendor's *own* uninstaller - nothing
is force-deleted and no service is ripped out from under itself.
"""

from __future__ import annotations

import ntpath
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field

IS_WINDOWS = sys.platform == "win32"
_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

MSI_GUID = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                      r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    patterns: tuple[str, ...]
    #: True when the app also controls fan curves, pump speed, DPI or macros.
    #: Removing it is safe, but those functions fall back to firmware/BIOS.
    cooling: bool
    note: str
    processes: tuple[str, ...] = ()
    official_tool: str | None = None


@dataclass
class InstalledApp:
    display_name: str
    version: str
    publisher: str
    uninstall_string: str
    quiet_uninstall: str
    product_code: str
    entry: CatalogEntry

    @property
    def cooling(self) -> bool:
        return self.entry.cooling

    @property
    def note(self) -> str:
        return self.entry.note


CATALOG: tuple[CatalogEntry, ...] = (
    # ---- ASUS -------------------------------------------------------------- #
    CatalogEntry(
        "ASUS Armoury Crate",
        (r"^Armoury Crate", r"ASUS Framework Service", r"Armoury Socket", r"AsusCertService"),
        True,
        "Also runs fan curves, Aura Sync and ASUS device profiles.",
        ("ArmouryCrate.UserSessionHelper", "ArmouryCrate.Service", "ArmourySocketServer"),
        'ASUS "Armoury Crate Uninstall Tool" - a plain uninstall famously leaves services behind.',
    ),
    CatalogEntry(
        "ASUS Aura / Lighting Control",
        (r"AURA", r"Lighting Control", r"AacKingstonDramHal", r"ASUS Motherboard Lighting"),
        False,
        "Pure lighting. Safe to remove.",
        ("LightingService",),
    ),
    CatalogEntry(
        "ASUS GPU Tweak",
        (r"GPU Tweak",),
        True,
        "Also does GPU fan curves and overclocking.",
        ("GPUTweak", "GPUTweakIII"),
    ),
    # ---- Corsair ----------------------------------------------------------- #
    CatalogEntry(
        "Corsair iCUE",
        (r"^iCUE", r"Corsair iCUE", r"Corsair Utility Engine", r"CORSAIR iCUE"),
        True,
        "Also drives AIO pump speed and fan curves. Without it the AIO runs on "
        "its firmware default - safe, often louder.",
        ("iCUE", "Corsair.Service"),
    ),
    # ---- MSI --------------------------------------------------------------- #
    CatalogEntry("MSI Mystic Light", (r"Mystic Light",), False,
                 "Pure lighting. Safe to remove.", ("MysticLight",)),
    CatalogEntry("MSI Center / Dragon Center",
                 (r"MSI Center", r"Dragon Center", r"MSI\.CentralServer"), True,
                 "Also runs fan profiles and system tuning.",
                 ("MSI Center", "MSI.CentralServer", "DCv2")),
    # ---- Gigabyte ---------------------------------------------------------- #
    CatalogEntry("Gigabyte RGB Fusion", (r"RGB Fusion", r"RGBFusion"), False,
                 "Pure lighting. Safe to remove.", ("RGBFusion", "GLedTray")),
    CatalogEntry("Gigabyte Control Center / AORUS Engine",
                 (r"Gigabyte Control Center", r"AORUS Engine", r"GIGABYTE APP Center"),
                 True, "Also runs fan curves and GPU tuning.",
                 ("GigabyteControlCenter", "AORUSEngine", "AppCenter")),
    # ---- ASRock ------------------------------------------------------------ #
    CatalogEntry("ASRock Polychrome RGB",
                 (r"Polychrome", r"ASRock RGB LED", r"ASRRGBLED"), False,
                 "Pure lighting. Safe to remove.", ("AsrRGBLedService",)),
    CatalogEntry("ASRock Motherboard Utility / A-Tuning",
                 (r"A-Tuning", r"ASRock Motherboard Utility"), True,
                 "Also runs fan tuning.", ("ATuning",)),
    # ---- Case / cooler vendors --------------------------------------------- #
    CatalogEntry("NZXT CAM", (r"NZXT CAM",), True,
                 "Also drives Kraken pump/fan curves and the LCD.",
                 ("NZXT CAM", "NZXT.CAM")),
    CatalogEntry("Lian Li L-Connect", (r"L-Connect",), True,
                 "Also controls fan speed on Lian Li hubs.", ("L-Connect",)),
    CatalogEntry("Cooler Master MasterPlus", (r"MasterPlus", r"Cooler Master"), True,
                 "Also runs cooler fan/pump profiles.", ("MasterPlus",)),
    CatalogEntry("Thermaltake TT RGB Plus", (r"TT RGB PLUS", r"Thermaltake"), True,
                 "Also controls fan speed on TT controllers.", ("TT RGB PLUS",)),
    CatalogEntry("Phanteks / DeepCool / Antec software",
                 (r"Phanteks", r"DeepCool", r"Antec.*RGB"), True,
                 "Mostly lighting, but some builds also drive PWM hubs or a "
                 "cooler display. Flagged as a precaution."),
    # ---- Peripherals ------------------------------------------------------- #
    CatalogEntry("Razer Synapse / Chroma",
                 (r"Razer Synapse", r"Razer Chroma", r"Razer Central"), False,
                 "Also stores mouse DPI, macros and key remaps. Onboard-memory "
                 "profiles survive; software-only ones do not.",
                 ("Razer Synapse Service", "RzSDKService")),
    CatalogEntry("Logitech G HUB / Gaming Software",
                 (r"Logitech G HUB", r"Logitech Gaming Software"), False,
                 "Also stores DPI and macro profiles.",
                 ("lghub", "lghub_agent", "LCore")),
    CatalogEntry("SteelSeries GG / Engine",
                 (r"SteelSeries GG", r"SteelSeries Engine"), False,
                 "Also stores device profiles and Sonar audio routing.",
                 ("SteelSeriesGG",)),
    CatalogEntry("HyperX NGENUITY", (r"NGENUITY",), False,
                 "Peripheral lighting and profiles.", ("ngenuity",)),
    # ---- RAM --------------------------------------------------------------- #
    CatalogEntry("Kingston FURY CTRL", (r"FURY CTRL", r"Kingston FURY"), False,
                 "Pure RAM lighting. Safe to remove.", ("KingstonFURYCTRL",)),
    CatalogEntry("G.SKILL Trident Z Lighting Control",
                 (r"Trident Z Lighting", r"G\.SKILL"), False,
                 "Pure RAM lighting. Safe to remove.", ("TridentZLightingControl",)),
    CatalogEntry("ADATA XPG / Patriot Viper RGB",
                 (r"XPG RGB", r"Viper RGB", r"ADATA RGB"), False,
                 "Pure RAM lighting. Safe to remove."),
)

_COMPILED = [(e, [re.compile(p, re.IGNORECASE) for p in e.patterns]) for e in CATALOG]


def match_catalog(display_name: str) -> CatalogEntry | None:
    """Which catalog entry, if any, this installed program is."""
    for entry, patterns in _COMPILED:
        if any(p.search(display_name) for p in patterns):
            return entry
    return None


# --------------------------------------------------------------------------- #
# scanning
# --------------------------------------------------------------------------- #

def _reg_str(key, name: str, default: str = "") -> str:
    """Read one string value, tolerating anything the registry throws at us.

    A module-level helper rather than a closure so it never captures a loop
    variable.
    """
    import winreg  # noqa: PLC0415

    try:
        return str(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return default


def scan_installed() -> list[InstalledApp]:
    """Walk the Windows uninstall registry for anything in the catalog."""
    if not IS_WINDOWS:
        return []
    import winreg  # noqa: PLC0415

    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    found: list[InstalledApp] = []
    seen: set[tuple[str, str]] = set()

    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    child = winreg.EnumKey(key, i)
                    sub = winreg.OpenKey(key, child)
                except OSError:
                    continue
                with sub:
                    display = _reg_str(sub, "DisplayName")
                    if not display.strip():
                        continue
                    if _reg_str(sub, "SystemComponent", "0") in ("1", "1L"):
                        continue

                    entry = match_catalog(display)
                    if entry is None:
                        continue
                    dedupe = (display, child)
                    if dedupe in seen:
                        continue
                    seen.add(dedupe)

                    found.append(InstalledApp(
                        display_name=display,
                        version=_reg_str(sub, "DisplayVersion"),
                        publisher=_reg_str(sub, "Publisher"),
                        uninstall_string=_reg_str(sub, "UninstallString"),
                        quiet_uninstall=_reg_str(sub, "QuietUninstallString"),
                        product_code=child,
                        entry=entry,
                    ))

    found.sort(key=lambda a: (a.cooling, a.entry.name, a.display_name))
    return found


# --------------------------------------------------------------------------- #
# removal
# --------------------------------------------------------------------------- #

def split_command(command: str) -> tuple[str, str]:
    """Split an UninstallString into (executable, arguments)."""
    command = command.strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        if end > 0:
            return command[1:end], command[end + 1:].strip()
    m = re.match(r"^(.+?\.exe)\s*(.*)$", command, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2).strip()
    return command, ""


@dataclass(frozen=True)
class UninstallPlan:
    executable: str
    args: list[str] = field(default_factory=list)
    #: False means we could not derive silent switches, so the vendor's own
    #: uninstaller window will open and the user clicks through it.
    silent: bool = False

    @property
    def usable(self) -> bool:
        return bool(self.executable)


def plan_uninstall(app: InstalledApp) -> UninstallPlan:
    # 1. The vendor gave us a quiet string. Best case.
    if app.quiet_uninstall.strip():
        exe, args = split_command(app.quiet_uninstall)
        return UninstallPlan(exe, args.split() if args else [], True)

    # 2. MSI product code - deterministic and safe.
    guid = app.product_code if MSI_GUID.fullmatch(app.product_code) else None
    if guid is None and "msiexec" in app.uninstall_string.lower():
        m = MSI_GUID.search(app.uninstall_string)
        guid = m.group(0) if m else None
    if guid:
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        return UninstallPlan(
            os.path.join(system_root, "System32", "msiexec.exe"),
            ["/x", guid, "/qn", "/norestart"], True,
        )

    if not app.uninstall_string.strip():
        return UninstallPlan("", [], False)

    exe, args = split_command(app.uninstall_string)
    arg_list = args.split() if args else []
    # ntpath, not os.path: uninstall strings are always Windows paths, and the
    # tests run on Linux where os.path would not split on backslashes.
    lower = ntpath.basename(exe).lower()

    # 3. Inno Setup
    if re.fullmatch(r"unins\d*\.exe", lower):
        return UninstallPlan(exe, arg_list + ["/VERYSILENT", "/SUPPRESSMSGBOXES",
                                              "/NORESTART"], True)
    # 4. NSIS
    if lower.startswith(("uninstall", "uninst")):
        return UninstallPlan(exe, arg_list + ["/S"], True)

    # 5. Unknown installer. Run it visibly rather than guessing switches that
    #    might do something other than uninstall.
    return UninstallPlan(exe, arg_list, False)


def _stop_processes(names: Iterable[str]) -> None:
    if not IS_WINDOWS:
        return
    for n in names:
        if not n:
            continue
        try:
            subprocess.run(["taskkill", "/F", "/IM", f"{n}.exe", "/T"],
                           capture_output=True, creationflags=_NO_WINDOW,
                           timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass


#: 0 ok, 1605 already gone, 3010 ok but reboot needed
OK_EXIT_CODES = {0, 1605, 3010}
CANCELLED = 1602


def uninstall(app: InstalledApp, timeout: int = 900) -> tuple[bool, str]:
    """Run one vendor uninstaller. Returns (ok, detail)."""
    _stop_processes(app.entry.processes)

    plan = plan_uninstall(app)
    if not plan.usable:
        return False, "no uninstaller registered"
    if not os.path.isfile(plan.executable) and "msiexec" not in plan.executable.lower():
        return False, f"uninstaller missing: {plan.executable}"

    try:
        proc = subprocess.run(
            [plan.executable, *plan.args],
            capture_output=plan.silent, timeout=timeout,
            creationflags=_NO_WINDOW if plan.silent else 0,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except OSError as err:
        return False, str(err)

    if proc.returncode in OK_EXIT_CODES:
        extra = " (reboot needed to finish)" if proc.returncode == 3010 else ""
        return True, f"removed{extra}"
    if proc.returncode == CANCELLED:
        return False, "cancelled"
    return False, f"uninstaller exit code {proc.returncode}"
