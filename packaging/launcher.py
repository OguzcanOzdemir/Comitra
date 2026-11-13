"""Entry point used by PyInstaller for both the GUI and the CLI executable."""

import multiprocessing
import os
import sys


def _main() -> int:
    from comitra.cli import main

    exe = os.path.basename(sys.executable).lower()
    argv = sys.argv[1:]
    # The console helper defaults to "--help" instead of opening the GUI.
    if exe.startswith("comitra-cli") and not argv:
        argv = ["--help"]
    return main(argv)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        code = _main()
    except SystemExit as exc:  # argparse --help/--version
        code = exc.code if isinstance(exc.code, int) else 0
    sys.exit(code or 0)
