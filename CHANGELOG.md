# Changelog

## 1.0.8

- Fix: on launch only the RAM modules appeared, and the rest showed up only
  after a manual refresh. OpenRGB answers its SDK port before it has finished
  enumerating hardware, so connecting the moment the port opens returns a
  partial list - the SMBus devices, because those are detected first - which
  then grows with no notification to the client. The app now polls until two
  consecutive reads agree.
- The same race affected the blackout at logon, which runs 30 seconds after
  login while OpenRGB may still be detecting. It would have blanked whatever
  had been found so far and reported success. Both the window and the CLI now
  wait.

## 1.0.7

- Closing the window now quits. There is no tray icon and no resident process.
  The tray only ever offered a one-click blackout, which the logon task does
  automatically and the Start Menu shortcut does on demand - so it was paying
  for itself with a permanently running elevated process on a machine where
  the app is opened perhaps twice a year.
- Consequences: `pystray` and `Pillow` are no longer dependencies, so the
  executable is smaller and there is one less LGPL library in the licensing
  story; and an installer can no longer stall on a running copy, which is what
  caused the "unable to automatically close all applications" error in 1.0.2.

## 1.0.6

- Fix: 1.0.5 shipped a stale copy of `gui.py`. It carried the new version
  number but none of the simplification, and it silently reverted the window
  icon and the tray notification added in 1.0.4. This release contains what
  1.0.5 was supposed to.

## 1.0.5

Simplification pass. Everything removed here was information the user could not
act on, or a control that did something the app can decide for itself.

- The three health rows are gone. Green ticks reading "yes, fine" said nothing;
  the checks matter only when one fails, so they now surface as a single amber
  panel that appears only then and carries the button that fixes it.
- The device table lost its Type and LED-count columns. Neither changed what
  anyone would do. The chosen mode stays, because it is the first thing to look
  at when a device refuses to go dark, and `rgboff-cli --list` still prints
  everything.
- The Refresh button is gone; opening the window re-checks automatically.
- Shorter option labels, no subtitle, no section heading, smaller window.

## 1.0.4

- The window and taskbar now show the app's own icon. PyInstaller's `--icon`
  only brands the executable; the Tk window kept its default feather because
  nothing set it. The .ico is bundled into the build and applied to the window
  and its dialogs.

## 1.0.3

- Fix: upgrading over a running copy stopped with "Setup was unable to
  automatically close all applications". RGB Off lives in the tray and its
  window-close handler hides rather than quits, so it ignored Restart Manager's
  WM_CLOSE. The installer now uses `CloseApplications=force`.
- The tray shows a one-time notification the first time the window is closed,
  so it is clear the app is still running and where to quit it.

## 1.0.2

- Device types now read as words - `MOTHERBOARD` became `Motherboard`,
  `HEADSET_STAND` became `Headset stand` - while acronyms like DRAM and GPU
  stay uppercase.
- Fix: on a short window the status line and the buttons were clipped, because
  the expanding device table was packed before them. The controls are now
  anchored to the bottom edge and the table takes what is left.
- Fix: the option checkboxes drew as white boxes on the dark background; they
  use tk's checkbutton, which honours the palette, instead of ttk's.

## 1.0.1

- Fix: the installer's "launch now" checkbox failed with `CreateProcess failed;
  code 740`. The app is manifested `requireAdministrator`, and Inno Setup's
  `[Run]` uses CreateProcess, which cannot elevate. The entry now uses
  `shellexec`. Installation itself was never affected.
- Fix: **Run setup** finished silently on a machine that was already set up, so
  it looked like the button did nothing. It now reports every step it checked
  or performed, and anything that still needs attention.
- Interface pass: consistent sentence case throughout (the primary button was
  shouting in all-caps), a health card with coloured status dots, a striped
  device table, hover states, and a busy state on the primary button.

## 1.0.0

First release.

- Desktop app: window plus system-tray icon, one button to blank every device
  OpenRGB can reach.
- Mode selection handles `Off`, `Static`, `Direct` and `Custom` by name, then
  falls back to whichever mode the controller flags as per-LED. Mode-specific
  colour slots are blanked before switching so a device never comes up in a
  remembered colour.
- Vendor software removal: registry scan against a catalog of ~20 programs,
  split into lighting-only and "also does fan/pump/DPI", removed through each
  vendor's own uninstaller.
- Setup installs OpenRGB and PawnIO via winget, enables the SDK server, and
  registers a logon task to keep it running.
- Optional blackout-at-logon task, for controllers with no persistent off state.
- 46 tests covering mode selection and uninstall planning, run against a fake
  OpenRGB client so no hardware is needed.
