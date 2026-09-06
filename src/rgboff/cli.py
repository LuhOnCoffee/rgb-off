"""Command line entry point.

With no arguments (and a console-less build) this opens the GUI. Everything the
GUI can do is also reachable here, which is what the logon task uses.
"""

from __future__ import annotations

import argparse
import sys
import time

from . import __version__
from .core import (
    REFRESH_SECONDS,
    OpenRGBUnavailable,
    apply_all,
    black,
    connect,
    describe_plan,
    device_type_of,
    parse_color,
    summarize,
    wait_for_devices,
)
from .elevation import is_admin
from .server import ensure_server, pawnio_installed


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rgboff",
        description="Turn off all RGB lighting via OpenRGB.",
    )
    p.add_argument("--off", action="store_true",
                   help="turn everything off and exit")
    p.add_argument("--list", action="store_true",
                   help="list detected devices and the mode each would use")
    p.add_argument("--color", metavar="RRGGBB",
                   help="set this colour instead of off, e.g. 202020")
    p.add_argument("--hold", action="store_true",
                   help=f"stay running and re-apply every {REFRESH_SECONDS}s, for "
                        "controllers that revert when the client disconnects")
    p.add_argument("--quiet", action="store_true",
                   help="only print problems (used by the logon task)")
    p.add_argument("--gui", action="store_true", help="open the window")
    p.add_argument("--version", action="version", version=f"rgboff {__version__}")
    return p


def _preflight(say) -> None:
    if not is_admin():
        say("NOTE: not running as administrator - RAM and GPU lighting will be "
            "invisible. Right-click the shortcut and Run as administrator.")
    if not pawnio_installed():
        say("NOTE: PawnIO is not installed - OpenRGB cannot reach the SMBus, so "
            "RAM, GPU and most motherboard controllers will not appear. "
            "Open the app and use Setup, or install it from https://pawnio.eu.")


def run_cli(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    loud = not args.quiet

    def say(text: str = "") -> None:
        if loud:
            print(text)

    if args.gui or not (args.off or args.list or args.color or args.hold):
        from .gui import main as gui_main  # noqa: PLC0415
        return gui_main()

    _preflight(say)

    ok, message = ensure_server()
    say(message)
    if not ok:
        print(message, file=sys.stderr)
        return 2

    try:
        client = connect(on_wait=say)
    except OpenRGBUnavailable as err:
        print(err, file=sys.stderr)
        return 2

    # The logon task runs 30 seconds after login, while OpenRGB may still be
    # enumerating. Without this the scheduled blackout would blank whatever had
    # been detected so far and report success.
    wait_for_devices(client, on_wait=say)
    devices = client.devices
    if not devices:
        print("OpenRGB detected zero devices. Usually: no administrator rights, "
              "PawnIO missing, or vendor software still holding the hardware.",
              file=sys.stderr)
        return 1

    if args.list:
        for i, dev in enumerate(devices):
            modes = ", ".join(m.name for m in dev.modes) or "-"
            print(f"[{i}] {dev.name}  ({device_type_of(dev)}, {len(dev.leds)} LEDs)")
            print(f"     modes:    {modes}")
            print(f"     will use: {describe_plan(dev)}")
        return 0

    want_off = args.color is None
    try:
        color = parse_color(args.color) if args.color else black()
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2

    results = apply_all(devices, color, want_off)
    for r in results:
        say(f"  {'OK  ' if r.ok else 'FAIL'} {r.name}  [{r.kind}]  -> {r.detail}")
    say("")
    say(summarize(results))

    failures = [r for r in results if not r.ok]
    if failures and args.quiet:
        for r in failures:
            print(f"FAIL {r.name}: {r.detail}", file=sys.stderr)

    if args.hold:
        say(f"Holding - re-applying every {REFRESH_SECONDS}s. Ctrl+C to stop.")
        try:
            while True:
                time.sleep(REFRESH_SECONDS)
                try:
                    apply_all(client.devices, color, want_off)
                except Exception:
                    # A dropped server or a vanished device shouldn't kill the
                    # holder; try again on the next tick.
                    pass
        except KeyboardInterrupt:
            pass

    return 1 if failures else 0


def main() -> int:
    try:
        return run_cli()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
