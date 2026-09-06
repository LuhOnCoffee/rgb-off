"""PyInstaller entry point for both the windowed and console builds.

With no arguments it opens the window; with --off / --list / --color it behaves
as a CLI. That is what lets the logon task reuse the same executable.
"""

import sys

from rgboff.cli import main

if __name__ == "__main__":
    sys.exit(main())
