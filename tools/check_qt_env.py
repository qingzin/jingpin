from __future__ import annotations

import platform
import sys


def main() -> int:
    print("=== Python Runtime ===")
    print(f"Python: {sys.version}")
    print(f"Executable: {sys.executable}")
    print(f"Platform: {platform.platform()}")
    print()

    print("=== Qt Check ===")
    try:
        from PySide6 import QtCore

        print("PySide6 import: OK")
        print(f"Qt version: {QtCore.__version__}")
        print(f"Qt library path: {QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibraryPath.LibrariesPath)}")
    except Exception as exc:
        print(f"PySide6 import: FAILED -> {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
