"""The desktop app: one window, and nothing left running once you close it.

Long operations (scanning, uninstalling, talking to OpenRGB) run on worker
threads and post results back through a queue, so the window never freezes.
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import __version__, vendors
from .autostart import (
    TASK_BLACKOUT,
    disable_blackout_task,
    enable_blackout_task,
    enable_server_task,
    task_exists,
)
from .core import (
    OpenRGBUnavailable,
    apply_all,
    black,
    connect,
    describe_plan,
    wait_for_devices,
)
from .elevation import is_admin, relaunch_as_admin
from .server import (
    OPENRGB_URL,
    PAWNIO_URL,
    enable_sdk_server_in_settings,
    ensure_server,
    find_openrgb,
    install_openrgb,
    install_pawnio,
    pawnio_installed,
)

# --------------------------------------------------------------------------- #
# palette and type
# --------------------------------------------------------------------------- #

BG = "#101216"        # window
SURFACE = "#181b21"   # cards
TABLE = "#1c2027"     # table body
BORDER = "#272c35"
TEXT = "#e6e9ee"
MUTED = "#929aa6"
FAINT = "#6c7480"
ACCENT = "#4f8cff"
ACCENT_HOVER = "#6699ff"
ACCENT_DOWN = "#3d76e0"
GOOD = "#46b17b"
WARN = "#dfa441"
BAD = "#e0605f"

TITLE_FONT = ("Segoe UI Semibold", 19)
SUB_FONT = ("Segoe UI", 10)
BODY_FONT = ("Segoe UI", 10)
LABEL_FONT = ("Segoe UI Semibold", 9)
BUTTON_FONT = ("Segoe UI Semibold", 12)


def icon_path() -> str | None:
    """The .ico, whether we are frozen by PyInstaller or running from source.

    PyInstaller's --icon only sets the icon on the executable; the Tk window
    keeps its default feather unless we set it ourselves.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    candidate = (Path(bundled) / "rgboff.ico" if bundled
                 else Path(__file__).resolve().parents[2] / "assets" / "rgboff.ico")
    try:
        return str(candidate) if candidate.is_file() else None
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# small widget helpers
# --------------------------------------------------------------------------- #

def card(parent: tk.Misc) -> tk.Frame:
    """A surface panel with a hairline border."""
    return tk.Frame(parent, bg=SURFACE, highlightbackground=BORDER,
                    highlightcolor=BORDER, highlightthickness=1, bd=0)


class ProblemBanner:
    """Appears only when a health check actually fails.

    Three green ticks reading "yes, fine" are three lines of nothing. The
    administrator / PawnIO / server checks matter precisely when one of them
    fails, so the panel earns its space only then - and when it does, it says
    what is wrong and offers the one button that fixes it.
    """

    def __init__(self, parent: tk.Misc, on_fix):
        self.frame = tk.Frame(parent, bg=SURFACE, highlightbackground=WARN,
                              highlightcolor=WARN, highlightthickness=1, bd=0)
        self.label = tk.Label(self.frame, text="", bg=SURFACE, fg=WARN,
                              font=BODY_FONT, anchor="w", justify="left",
                              wraplength=440)
        self.label.pack(side="left", fill="x", expand=True, padx=(14, 10), pady=12)
        self.button = quiet_button(self.frame, "Fix this", on_fix)
        self.button.pack(side="right", padx=14, pady=10)
        self._shown = False

    def show(self, problems: list[str], before: tk.Misc, padx: int) -> None:
        self.label.configure(text="\n".join(problems))
        if not self._shown:
            self.frame.pack(fill="x", padx=padx, pady=(0, 12), before=before)
            self._shown = True

    def hide(self) -> None:
        if self._shown:
            self.frame.pack_forget()
            self._shown = False


class PrimaryButton(tk.Button):
    """Flat accent button with hover and a busy state."""

    def __init__(self, parent: tk.Misc, text: str, command):
        super().__init__(parent, text=text, command=command, bg=ACCENT, fg="white",
                         activebackground=ACCENT_DOWN, activeforeground="white",
                         relief="flat", bd=0, highlightthickness=0,
                         font=BUTTON_FONT, height=2, cursor="hand2")
        self._label = text
        self.bind("<Enter>", lambda _e: self._hover(True))
        self.bind("<Leave>", lambda _e: self._hover(False))

    def _hover(self, on: bool) -> None:
        if str(self["state"]) != "disabled":
            self.configure(bg=ACCENT_HOVER if on else ACCENT)

    def busy(self, text: str = "Working…") -> None:
        self.configure(text=text, state="disabled", bg=BORDER, fg=MUTED, cursor="")

    def ready(self) -> None:
        self.configure(text=self._label, state="normal", bg=ACCENT, fg="white",
                       cursor="hand2")


def dark_check(parent: tk.Misc, text: str, variable, command) -> tk.Checkbutton:
    """ttk's checkbutton renders a white box on a dark theme; tk's obeys colours."""
    return tk.Checkbutton(parent, text=text, variable=variable, command=command,
                          bg=BG, fg=TEXT, activebackground=BG, activeforeground=TEXT,
                          selectcolor=BORDER, font=BODY_FONT, anchor="w",
                          highlightthickness=0, bd=0, cursor="hand2")


def quiet_button(parent: tk.Misc, text: str, command) -> tk.Button:
    b = tk.Button(parent, text=text, command=command, bg=SURFACE, fg=TEXT,
                  activebackground=BORDER, activeforeground=TEXT, relief="flat",
                  bd=0, highlightbackground=BORDER, highlightthickness=1,
                  font=BODY_FONT, padx=14, pady=6, cursor="hand2")
    b.bind("<Enter>", lambda _e: b.configure(bg=BORDER))
    b.bind("<Leave>", lambda _e: b.configure(bg=SURFACE))
    return b


# --------------------------------------------------------------------------- #
# main window
# --------------------------------------------------------------------------- #

class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("RGB Off")
        self.root.geometry("620x520")
        self.root.minsize(560, 460)
        self.root.configure(bg=BG)

        icon = icon_path()
        if icon:
            try:
                # default=True so Toplevels (the vendor dialog) inherit it.
                self.root.iconbitmap(default=icon)
            except tk.TclError:
                pass

        self.ui_queue: queue.Queue = queue.Queue()
        self.devices: list = []
        self.client = None
        self._hold_stop = threading.Event()

        self._build_style()
        self._build_widgets()

        # Closing the window quits. There is no tray icon and no resident
        # process: the logon task does the recurring work, and the Start Menu
        # has a "Turn RGB off now" shortcut for the manual case.
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

        self.root.after(100, self._drain_queue)
        self.root.after(200, lambda: self.run_async(self.refresh_all))

    # ---- styling --------------------------------------------------------- #

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=BG,
                        font=BODY_FONT)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=TEXT, font=BODY_FONT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED)
        style.configure("Section.TLabel", background=BG, foreground=FAINT,
                        font=LABEL_FONT)

        style.configure("TCheckbutton", background=BG, foreground=TEXT,
                        font=BODY_FONT, focuscolor=BG)
        style.map("TCheckbutton",
                  background=[("active", BG)],
                  indicatorcolor=[("selected", ACCENT), ("!selected", BORDER)])

        style.configure("Treeview", background=TABLE, fieldbackground=TABLE,
                        foreground=TEXT, borderwidth=0, rowheight=27,
                        font=BODY_FONT)
        style.configure("Treeview.Heading", background=SURFACE, foreground=FAINT,
                        borderwidth=0, font=LABEL_FONT, padding=(8, 6))
        style.map("Treeview.Heading", background=[("active", SURFACE)])
        style.map("Treeview", background=[("selected", "#2a3242")],
                  foreground=[("selected", TEXT)])
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # ---- widgets --------------------------------------------------------- #

    def _build_widgets(self) -> None:
        gutter = 20

        self.gutter = gutter

        # ---- header ------------------------------------------------------ #
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=gutter, pady=(18, 14))
        tk.Label(header, text="RGB Off", font=TITLE_FONT, bg=BG, fg=TEXT).pack(side="left")
        tk.Label(header, text=f"v{__version__}", font=SUB_FONT, bg=BG, fg=FAINT
                 ).pack(side="left", padx=(10, 0), pady=(8, 0))

        # Bottom half first, so the device list absorbs the leftover height and
        # can never push the controls or the status line off a short window.
        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(side="bottom", fill="x")

        self.btn_off = PrimaryButton(bottom, "Turn everything off",
                                     lambda: self.run_async(self.do_blackout))
        self.btn_off.pack(fill="x", padx=gutter, pady=(16, 12))

        opts = tk.Frame(bottom, bg=BG)
        opts.pack(fill="x", padx=gutter)

        self.var_logon = tk.BooleanVar(value=task_exists(TASK_BLACKOUT))
        dark_check(opts, "Turn off automatically at logon",
                   self.var_logon, self.toggle_logon).pack(anchor="w", pady=1)

        self.var_hold = tk.BooleanVar(value=False)
        dark_check(opts, "Keep re-applying while open",
                   self.var_hold, self.toggle_hold).pack(anchor="w", pady=1)

        actions = tk.Frame(bottom, bg=BG)
        actions.pack(fill="x", padx=gutter, pady=(14, 0))
        quiet_button(actions, "Remove vendor software…",
                     self.open_vendor_dialog).pack(side="left")
        quiet_button(actions, "Setup",
                     lambda: self.run_async(self.do_setup)).pack(side="left", padx=8)

        tk.Frame(bottom, bg=BORDER, height=1).pack(fill="x", pady=(16, 0))
        self.status = tk.Label(bottom, text="Starting…", font=SUB_FONT, bg=BG,
                               fg=MUTED, anchor="w", wraplength=620, justify="left")
        self.status.pack(fill="x", padx=gutter, pady=(8, 12))

        # ---- the device list fills what remains -------------------------- #
        table_wrap = card(self.root)
        table_wrap.pack(side="top", fill="both", expand=True, padx=gutter)
        self.table_wrap = table_wrap

        # Built last, shown only when a check fails - see ProblemBanner.
        self.banner = ProblemBanner(self.root,
                                    lambda: self.run_async(self.do_setup))

        # Two columns, no headings. Type and LED count were decoration - they
        # never changed what the user would do. The mode name stays because it
        # is the first thing to look at when a device refuses to go dark, and
        # `rgboff-cli --list` still prints everything.
        self.tree = ttk.Treeview(table_wrap, columns=("mode",), show="tree",
                                 height=6, selectmode="none")
        self.tree.column("#0", anchor="w", stretch=True)
        self.tree.column("mode", width=130, anchor="e", stretch=False)
        self.tree.tag_configure("odd", background="#1a1e25")
        self.tree.tag_configure("even", background=TABLE)
        self.tree.pack(fill="both", expand=True, padx=1, pady=1)

    # ---- threading plumbing ---------------------------------------------- #

    def request(self, fn, *args) -> None:
        """Call a UI-thread function from any thread."""
        self.ui_queue.put((fn, args))

    def run_async(self, fn, *args) -> None:
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _drain_queue(self) -> None:
        try:
            while True:
                fn, args = self.ui_queue.get_nowait()
                try:
                    fn(*args)
                except Exception as err:               # never kill the loop
                    self.set_status(f"Error: {err}")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def _status(self, text: str) -> None:
        self.request(self.set_status, text)

    # ---- health ----------------------------------------------------------- #

    def refresh_all(self) -> None:
        self._status("Checking…")

        problems: list[str] = []
        if not is_admin():
            problems.append("Not running as administrator — RAM and GPU "
                            "lighting will be invisible.")
        if not pawnio_installed():
            problems.append("PawnIO is not installed — RAM, GPU and most "
                            "motherboards will not appear.")

        ok, message = ensure_server()
        if not ok:
            problems.append(message)

        self.request(self._set_problems, problems)

        if not ok:
            self.request(self._fill_tree, [])
            self._status("OpenRGB is not reachable.")
            return

        try:
            self.client = connect()
            # OpenRGB answers its port before it has finished detecting, so a
            # list read straight after connecting is usually just the SMBus
            # devices. Wait for it to stop growing.
            wait_for_devices(self.client, on_wait=self._status)
            self.devices = list(self.client.devices)
        except OpenRGBUnavailable as err:
            self._status(str(err))
            return

        rows = [(d.name, describe_plan(d)) for d in self.devices]
        self.request(self._fill_tree, rows)
        self._status(f"{len(rows)} devices ready." if rows
                     else "No devices detected.")

    def _set_problems(self, problems: list[str]) -> None:
        if problems:
            self.banner.show(problems, before=self.table_wrap, padx=self.gutter)
        else:
            self.banner.hide()

    def _fill_tree(self, rows) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, (name, mode) in enumerate(rows):
            self.tree.insert("", "end", text="  " + name, values=(mode + "  ",),
                             tags=("even" if i % 2 else "odd",))

    # ---- actions ---------------------------------------------------------- #

    def do_blackout(self) -> None:
        self.request(self.btn_off.busy, "Turning off…")
        try:
            if self.client is None:
                self.client = connect()
                wait_for_devices(self.client)
            results = apply_all(self.client.devices, black(), True)
        except Exception as err:
            self._status(f"Failed: {err}")
            return
        finally:
            self.request(self.btn_off.ready)

        failed = [r for r in results if not r.ok]
        if failed:
            self._status(f"{len(results) - len(failed)} of {len(results)} dark. "
                         f"Refused: {', '.join(r.name for r in failed)}")
        else:
            self._status(f"All {len(results)} devices are dark.")

    def do_setup(self) -> None:
        """Install what's missing, then report what actually happened.

        Everything here is idempotent, so on a machine that is already set up
        it is a no-op - which is exactly why it has to say so out loud rather
        than finishing silently.
        """
        if not is_admin():
            self.request(self.offer_elevation)
            return

        done: list[str] = []
        problems: list[str] = []

        self._status("Checking PawnIO…")
        if pawnio_installed():
            done.append("PawnIO already installed")
        else:
            ok, detail = install_pawnio()
            if ok:
                done.append("PawnIO installed (reboot to load the driver)")
            else:
                problems.append(f"PawnIO: {detail} — get it from {PAWNIO_URL}")

        self._status("Checking OpenRGB…")
        if find_openrgb() is None:
            ok, detail = install_openrgb()
            if ok:
                done.append("OpenRGB installed")
            else:
                problems.append(f"OpenRGB: {detail} — get it from {OPENRGB_URL}")
        else:
            done.append("OpenRGB already installed")

        ok, detail = enable_sdk_server_in_settings()
        done.append("SDK server enabled in OpenRGB settings" if ok
                    else f"OpenRGB.json not updated ({detail})")

        exe = find_openrgb()
        if exe is not None:
            ok, detail = enable_server_task(exe)
            done.append("Logon task for the OpenRGB server registered" if ok
                        else f"Server logon task failed ({detail})")

        self.refresh_all()

        summary = "Setup: " + "; ".join(done) + "."
        if problems:
            summary += "  Needs attention — " + "; ".join(problems)
        self._status(summary)

    def offer_elevation(self) -> None:
        if messagebox.askyesno(
            "Administrator needed",
            "Installing drivers and reaching RAM and GPU lighting needs "
            "administrator rights.\n\nRestart RGB Off as administrator now?",
        ):
            if relaunch_as_admin():
                self.quit_app()

    def toggle_logon(self) -> None:
        if self.var_logon.get():
            ok, detail = enable_blackout_task(hold=False)
            self.set_status("RGB will be turned off 30 seconds after each logon."
                            if ok else f"Could not register the task: {detail}")
            if not ok:
                self.var_logon.set(False)
        else:
            disable_blackout_task()
            self.set_status("Automatic blackout at logon removed.")

    def toggle_hold(self) -> None:
        if self.var_hold.get():
            self._hold_stop.clear()
            self.run_async(self._hold_loop)
            self.set_status("Holding — re-applying every few seconds.")
        else:
            self._hold_stop.set()
            self.set_status("Stopped holding.")

    def _hold_loop(self) -> None:
        from .core import REFRESH_SECONDS  # noqa: PLC0415

        while not self._hold_stop.wait(REFRESH_SECONDS):
            try:
                if self.client is None:
                    self.client = connect()
                apply_all(self.client.devices, black(), True)
            except Exception:
                # A dropped server or a vanished device shouldn't end the hold.
                pass

    # ---- vendor software -------------------------------------------------- #

    def open_vendor_dialog(self) -> None:
        VendorDialog(self)

    # ---- window / lifecycle ----------------------------------------------- #

    def quit_app(self) -> None:
        self._hold_stop.set()
        try:
            if self.client is not None:
                self.client.disconnect()
        except Exception:
            pass
        self.root.quit()
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


# --------------------------------------------------------------------------- #
# vendor removal dialog
# --------------------------------------------------------------------------- #

class VendorDialog:
    def __init__(self, app: App):
        self.app = app
        # One list of (app, checkbox) pairs rather than two parallel lists:
        # a re-scan on the worker thread can no longer desync them.
        self.rows: list[tuple[vendors.InstalledApp, tk.BooleanVar]] = []

        self.win = tk.Toplevel(app.root)
        self.win.title("Vendor RGB software")
        self.win.geometry("760x560")
        self.win.minsize(640, 460)
        self.win.configure(bg=BG)
        self.win.transient(app.root)

        tk.Label(self.win, text="Vendor RGB software", font=TITLE_FONT, bg=BG,
                 fg=TEXT).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(self.win, bg=BG, fg=MUTED, font=SUB_FONT, wraplength=700,
                 justify="left", anchor="w",
                 text="These apps hold the lighting controllers open and re-paint them, "
                      "so they undo the blackout seconds after it runs. Removal uses each "
                      "vendor's own uninstaller — nothing is force-deleted."
                 ).pack(anchor="w", padx=20, pady=(0, 12))

        body_card = card(self.win)
        body_card.pack(fill="both", expand=True, padx=20)

        canvas = tk.Canvas(body_card, bg=SURFACE, highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(body_card, orient="vertical", command=canvas.yview)
        self.body = tk.Frame(canvas, bg=SURFACE)
        self.body.bind("<Configure>",
                       lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=12)

        bar = tk.Frame(self.win, bg=BG)
        bar.pack(fill="x", padx=20, pady=(14, 0))
        quiet_button(bar, "Remove selected",
                     lambda: app.run_async(self.remove_selected)).pack(side="left")
        quiet_button(bar, "Close", self.win.destroy).pack(side="right")

        self.status = tk.Label(self.win, text="Scanning…", font=SUB_FONT, bg=BG,
                               fg=MUTED, anchor="w", wraplength=700, justify="left")
        self.status.pack(fill="x", padx=20, pady=(10, 16))

        app.run_async(self.scan)

    def scan(self) -> None:
        found = vendors.scan_installed()
        self.app.request(self._render, found)

    def _render(self, found: list[vendors.InstalledApp]) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self.rows = []

        if not found:
            tk.Label(self.body, text="Nothing found — no vendor RGB software "
                                     "is installed.", bg=SURFACE, fg=GOOD,
                     font=BODY_FONT).pack(anchor="w", pady=10, padx=4)
            self.status.configure(text="")
            return

        safe = [a for a in found if not a.cooling]
        careful = [a for a in found if a.cooling]

        if safe:
            self._heading("SAFE TO REMOVE — LIGHTING ONLY", GOOD, first=True)
            for a in safe:
                self._row(a, default=True)

        if careful:
            self._heading("DOES MORE THAN RGB — READ FIRST", WARN, first=not safe)
            for a in careful:
                self._row(a, default=False)

        self.status.configure(
            text=f"{len(found)} found. Cooling and input apps are unticked by default "
                 "— fan control falls back to BIOS or firmware curves."
        )

    def _heading(self, text: str, colour: str, first: bool) -> None:
        tk.Label(self.body, text=text, bg=SURFACE, fg=colour, font=LABEL_FONT
                 ).pack(anchor="w", pady=((2 if first else 16), 4), padx=4)

    def _row(self, app_entry: vendors.InstalledApp, default: bool) -> None:
        var = tk.BooleanVar(value=default)
        self.rows.append((app_entry, var))

        frame = tk.Frame(self.body, bg=SURFACE)
        frame.pack(fill="x", anchor="w", pady=3, padx=4)

        label = f"{app_entry.display_name}  {app_entry.version}".strip()
        cb = tk.Checkbutton(frame, text=label, variable=var, bg=SURFACE, fg=TEXT,
                            activebackground=SURFACE, activeforeground=TEXT,
                            selectcolor=BORDER, font=BODY_FONT, anchor="w",
                            highlightthickness=0, bd=0, cursor="hand2")
        cb.pack(anchor="w")

        tk.Label(frame, text=app_entry.note, bg=SURFACE, fg=MUTED, font=SUB_FONT,
                 wraplength=620, justify="left", anchor="w").pack(anchor="w", padx=(26, 0))

        if app_entry.entry.official_tool:
            tk.Label(frame, text="Vendor tool: " + app_entry.entry.official_tool,
                     bg=SURFACE, fg=WARN, font=SUB_FONT, wraplength=620,
                     justify="left", anchor="w").pack(anchor="w", padx=(26, 0))

    def _say(self, text: str) -> None:
        self.app.request(lambda t=text: self.status.configure(text=t))

    def remove_selected(self) -> None:
        targets = [a for a, v in self.rows if v.get()]
        if not targets:
            self._say("Nothing ticked.")
            return
        if not is_admin():
            self.app.request(self.app.offer_elevation)
            return

        failures: list[str] = []
        total = len(targets)
        for i, app_entry in enumerate(targets, 1):
            self._say(f"Removing {app_entry.display_name} ({i} of {total})…")
            ok, detail = vendors.uninstall(app_entry)
            if not ok:
                failures.append(f"{app_entry.display_name} ({detail})")

        if failures:
            self._say("Could not remove: " + "; ".join(failures)
                      + " — try Settings > Apps > Installed apps.")
        else:
            self._say("Done. Reboot before the next blackout so the old services "
                      "are really gone.")
        self.app.run_async(self.scan)


def main() -> int:
    if sys.platform != "win32":
        print("RGB Off is a Windows app.", file=sys.stderr)
        return 2
    return App().run()
