"""Scheduled tasks: keep the OpenRGB server up, and blank the LEDs at logon.

Most controllers reset to rainbow on power-up and only some can store an "off"
state - Corsair DDR4 and Gigabyte boards, for instance, expose no Off or Static
mode at all. The logon task is what makes "off" stick across reboots.

Tasks are created from XML via schtasks so the 30-second start delay and
"run with highest privileges" both survive; the PowerShell cmdlets are less
consistent about the delay across Windows builds.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

TASK_SERVER = "OpenRGB SDK Server"
TASK_BLACKOUT = "RGB Off at Logon"

_TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{description}</Description>
    <URI>\\{name}</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{user}</UserId>
      <Delay>{delay}</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>StopExisting</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _current_user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    user = os.environ.get("USERNAME", "")
    return f"{domain}\\{user}" if domain and user else user


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _schtasks(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          timeout=60, creationflags=_NO_WINDOW)


def task_exists(name: str) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return _schtasks(["/Query", "/TN", name]).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def create_task(name: str, description: str, command: str, arguments: str = "",
                delay: str = "PT30S") -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "not Windows"

    xml = _TASK_XML.format(
        name=_escape(name), description=_escape(description),
        user=_escape(_current_user()), delay=delay,
        command=_escape(command), arguments=_escape(arguments),
    )

    # schtasks /XML insists on UTF-16 with a BOM.
    tmp = Path(tempfile.gettempdir()) / f"rgboff-{abs(hash(name))}.xml"
    try:
        tmp.write_text(xml, encoding="utf-16")
        result = _schtasks(["/Create", "/TN", name, "/XML", str(tmp), "/F"])
        if result.returncode == 0:
            return True, "registered"
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        return False, detail[-1] if detail else f"schtasks exit {result.returncode}"
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def delete_task(name: str) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "not Windows"
    try:
        result = _schtasks(["/Delete", "/TN", name, "/F"])
        return (result.returncode == 0,
                "removed" if result.returncode == 0 else "not present")
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)


# --------------------------------------------------------------------------- #
# the two tasks this app uses
# --------------------------------------------------------------------------- #

def app_command() -> tuple[str, str]:
    """(command, base arguments) for re-launching this app.

    Frozen by PyInstaller -> the exe itself. Running from source -> python -m.
    """
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    return sys.executable, "-m rgboff"


def enable_server_task(openrgb_exe: Path) -> tuple[bool, str]:
    return create_task(
        TASK_SERVER,
        "Keeps the OpenRGB SDK server running so RGB Off can reach the hardware.",
        str(openrgb_exe), "--server --startminimized", delay="PT10S",
    )


def enable_blackout_task(hold: bool = False) -> tuple[bool, str]:
    command, base = app_command()
    args = f'{base} --off --quiet'.strip()
    if hold:
        args += " --hold"
    return create_task(
        TASK_BLACKOUT,
        "Turns all RGB lighting off shortly after logon.",
        command, args, delay="PT30S",
    )


def disable_blackout_task() -> tuple[bool, str]:
    return delete_task(TASK_BLACKOUT)


def disable_server_task() -> tuple[bool, str]:
    return delete_task(TASK_SERVER)
