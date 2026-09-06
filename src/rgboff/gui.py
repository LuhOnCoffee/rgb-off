"""The desktop app: a window plus a system-tray icon.

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
    device_type_of,
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
DOT_FONT = ("Segoe UI", 11)

DOT = "●"


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
# tray icon
# --------------------------------------------------------------------------- #

def _tray_image():
    """A small dark-bulb icon drawn at runtime, so no asset file is needed."""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 6, 56, 48), fill=(32, 34, 40, 255), outline=(120, 126, 138, 255), width=3)
    d.rectangle((26, 46, 38, 58), fill=(120, 126, 138, 255))
    d.line((16, 52, 48, 12), fill=(224, 92, 92, 255), width=5)
    return img


class Tray:
    """Wraps pystray so the app still runs if pystray/Pillow are missing."""

    def __init__(self, app: App):
        self.app = app
        self.icon = None
        try:
            import pystray  # noqa: PLC0415

            self.icon = pystray.Icon(
                "rgboff", _tray_image(), "RGB Off",
                menu=pystray.Menu(
                    pystray.MenuItem("Turn everything off", self._off, default=True),
                    pystray.MenuItem("Open RGB Off", self._show),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Quit", self._quit),
                ),
            )
        except Exception:
            self.icon = None

    @property
    def available(self) -> bool:
        return self.icon is not None

    def start(self) -> None:
        if self.icon:
            threading.Thread(target=self.icon.run, daemon=True).start()

    def stop(self) -> None:
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass

    def notify(self, title: str, message: str) -> None:
        """Best effort - not every pystray backend implements notifications."""
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    def _off(self, *_):
        self.app.request(lambda: self.app.run_async(self.app.do_blackout))

    def _show(self, *_):
        self.app.request(self.app.show_window)

    def _quit(self, *_):
        self.app.request(self.app.quit_app)


# --------------------------------------------------------------------------- #
# small widget helpers
# --------------------------------------------------------------------------- #

def card(parent: tk.Misc) -> tk.Frame:
    """A surface panel with a hairline border."""
    return tk.Frame(parent, bg=SURFACE, highlightbackground=BORDER,
                    highlightcolor=BORDER, highlightthickness=1, bd=0)


class StatusRow:
    """One health indicator: a coloured dot, a name, and a state sentence."""

    def __init__(self, parent: tk.Misc, name: str, row: int):
        self.dot = tk.Label(parent, text=DOT, font=DOT_FONT, bg=SURFACE, fg=FAINT)
        self.dot.grid(row=row, column=0, sticky="w", padx=(14, 8), pady=3)

        self.name = tk.Label(parent, text=name, font=LABEL_FONT, bg=SURFACE, fg=TEXT,
                             anchor="w", width=15)
        self.name.grid(row=row, column=1, sticky="w", pady=3)

        self.state = tk.Label(parent, text="checking…", font=BODY_FONT, bg=SURFACE,
                              fg=MUTED, anchor="w", justify="left")
        self.state.grid(row=row, column=2, sticky="w", padx=(0, 14), pady=3)

    def set(self, ok: bool, text: str) -> None:
        self.dot.configure(fg=GOOD if ok else WARN)
        self.state.configure(text=text, fg=MUTED if ok else WARN)


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
        self.root.geometry("780x620")
        self.root.minsize(700, 560)
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
        self._hide_explained = False

        self._build_style()
        self._build_widgets()

        self.tray = Tray(self)
        self.tray.start()
        if self.tray.available:
            self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        else:
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

        # ---- header ------------------------------------------------------ #
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=gutter, pady=(18, 4))
        tk.Label(header, text="RGB Off", font=TITLE_FONT, bg=BG, fg=TEXT).pack(side="left")
        tk.Label(header, text=f"v{__version__}", font=SUB_FONT, bg=BG, fg=FAINT
                 ).pack(side="left", padx=(10, 0), pady=(8, 0))
        tk.Label(header, text="Every LED OpenRGB can reach", font=SUB_FONT,
                 bg=BG, fg=MUTED).pack(side="right", pady=(8, 0))

        # ---- health card ------------------------------------------------- #
        status_card = card(self.root)
        status_card.pack(fill="x", padx=gutter, pady=(10, 0))
        status_card.columnconfigure(2, weight=1)

        self.row_admin = StatusRow(status_card, "Administrator", 0)
        self.row_pawnio = StatusRow(status_card, "PawnIO driver", 1)
        self.row_server = StatusRow(status_card, "OpenRGB server", 2)

        self.btn_setup = quiet_button(status_card, "Run setup",
                                      lambda: self.run_async(self.do_setup))
        self.btn_setup.grid(row=0, column=3, rowspan=3, sticky="e", padx=14, pady=12)

        # ---- devices ----------------------------------------------------- #
        tk.Label(self.root, text="DETECTED DEVICES", font=LABEL_FONT, bg=BG,
                 fg=FAINT).pack(anchor="w", padx=gutter, pady=(18, 6))

        # Everything below the table is packed from the bottom edge FIRST, so
        # the table absorbs whatever height is left over. Packing top-down
        # instead lets an expanding table push the controls and the status line
        # off a short window.
        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(side="bottom", fill="x")

        self.btn_off = PrimaryButton(bottom, "Turn everything off",
                                     lambda: self.run_async(self.do_blackout))
        self.btn_off.pack(fill="x", padx=gutter, pady=(16, 12))

        opts = tk.Frame(bottom, bg=BG)
        opts.pack(fill="x", padx=gutter)

        self.var_logon = tk.BooleanVar(value=task_exists(TASK_BLACKOUT))
        dark_check(opts, "Turn RGB off automatically after each logon",
                   self.var_logon, self.toggle_logon).pack(anchor="w", pady=1)

        self.var_hold = tk.BooleanVar(value=False)
        dark_check(opts, "Keep re-applying while this window is open",
                   self.var_hold, self.toggle_hold).pack(anchor="w", pady=1)

        actions = tk.Frame(bottom, bg=BG)
        actions.pack(fill="x", padx=gutter, pady=(14, 0))
        quiet_button(actions, "Refresh",
                     lambda: self.run_async(self.refresh_all)).pack(side="left")
        quiet_button(actions, "Remove vendor software…",
                     self.open_vendor_dialog).pack(side="left", padx=8)

        tk.Frame(bottom, bg=BORDER, height=1).pack(fill="x", pady=(16, 0))
        self.status = tk.Label(bottom, text="Starting…", font=SUB_FONT, bg=BG,
                               fg=MUTED, anchor="w", wraplength=720, justify="left")
        self.status.pack(fill="x", padx=gutter, pady=(8, 12))

        # ---- the table fills what remains -------------------------------- #
        table_wrap = card(self.root)
        table_wrap.pack(side="top", fill="both", expand=True, padx=gutter)

        cols = ("type", "leds", "mode")
        self.tree = ttk.Treeview(table_wrap, columns=cols, show="tree headings",
                                 height=8, selectmode="none")
        self.tree.heading("#0", text="Device", anchor="w")
        self.tree.heading("type", text="Type", anchor="w")
        self.tree.heading("leds", text="LEDs", anchor="e")
        self.tree.heading("mode", text="Will use", anchor="w")
        self.tree.column("#0", width=310, anchor="w", stretch=True)
        self.tree.column("type", width=120, anchor="w", stretch=False)
        self.tree.column("leds", width=64, anchor="e", stretch=False)
        self.tree.column("mode", width=150, anchor="w", stretch=False)
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
        admin = is_admin()
        pawn = pawnio_installed()

        self.request(self.row_admin.set, admin,
                     "Running elevated" if admin
                     else "Not elevated — RAM and GPU lighting stay invisible")
        self.request(self.row_pawnio.set, pawn,
                     "Installed — SMBus reachable" if pawn
                     else "Missing — RAM, GPU and most boards will not appear")

        ok, message = ensure_server()
        self.request(self.row_server.set, ok,
                     "Running on 127.0.0.1:6742" if ok else message)
        if not ok:
            self.request(self._fill_tree, [])
            self._status(message)
            return

        try:
            self.client = connect()
            self.devices = list(self.client.devices)
        except OpenRGBUnavailable as err:
            self._status(str(err))
            return

        rows = [(d.name, device_type_of(d), len(getattr(d, "leds", [])),
                 describe_plan(d)) for d in self.devices]
        self.request(self._fill_tree, rows)
        self._status(f"{len(rows)} device(s) detected."
                     if rows else "No devices detected.")

    def _fill_tree(self, rows) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, (name, kind, leds, mode) in enumerate(rows):
            self.tree.insert("", "end", text="  " + name,
                             values=(kind, leds, mode),
                             tags=("even" if i % 2 else "odd",))

    # ---- actions ---------------------------------------------------------- #

    def do_blackout(self) -> None:
        self.request(self.btn_off.busy, "Turning off…")
        try:
            if self.client is None:
                self.client = connect()
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

        self.request(lambda: self.btn_setup.configure(text="Working…",
                                                      state="disabled"))
        done: list[str] = []
        problems: list[str] = []
        try:
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
        finally:
            self.request(lambda: self.btn_setup.configure(text="Run setup",
                                                          state="normal"))

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

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self) -> None:
        self.root.withdraw()
        if not self._hide_explained:
            self._hide_explained = True
            self.tray.notify("RGB Off is still running",
                             "It is in the notification area. Right-click the "
                             "icon and choose Quit to exit.")

    def quit_app(self) -> None:
        self._hold_stop.set()
        self.tray.stop()
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
