# Security policy

## Reporting a vulnerability

Use GitHub's [private vulnerability reporting](https://github.com/LuhOnCoffee/rgb-off/security/advisories/new)
rather than a public issue. I'll respond as quickly as I can — this is a personal
project, so expect days rather than hours.

## What this software actually does

Worth knowing before you assess it:

- **It runs elevated.** `RGBOff.exe` is manifested `requireAdministrator`.
  Reaching RAM, GPU and motherboard lighting goes through the SMBus, and PawnIO
  only grants that to an elevated process.
- **It creates scheduled tasks** that run at logon with highest privileges — one
  for the OpenRGB server, one optional blackout. Both are removed by the
  uninstaller, and are visible in Task Scheduler as `OpenRGB SDK Server` and
  `RGB Off at Logon`.
- **It can uninstall other software.** The vendor-removal feature invokes each
  vendor's own uninstaller from the Windows registry. It never force-deletes
  files or services, and it only acts on programs the user has ticked.
- **It runs `winget install`** for OpenRGB and PawnIO when you press Run setup.
- **PawnIO is a kernel driver** developed by a third party. RGB Off installs it
  through winget but does not vendor or modify it. Its security properties are
  its own — see <https://pawnio.eu>.

## Binaries are not code-signed

Releases are unsigned, so SmartScreen warns and you cannot verify the publisher
from the file itself. If that matters to you, build from source — the release
workflow is in the repository and does nothing you can't run locally.

## Scope

In scope: anything in this repository. Out of scope: vulnerabilities in OpenRGB,
PawnIO, or vendor software, which should go to those projects directly.
