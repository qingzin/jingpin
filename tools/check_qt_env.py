from __future__ import annotations

import os
import platform
import sys
from pathlib import Path


def main() -> int:
    print("=== Python ===")
    print(sys.version)
    print("executable:", sys.executable)
    print("base_prefix:", sys.base_prefix)
    print("platform:", platform.platform())

    print("\n=== Imports ===")
    try:
        import PySide6  # type: ignore
        from PySide6 import QtCore  # type: ignore
    except Exception as exc:
        print("PySide6 导入失败:", exc)
        return 1

    print("PySide6:", getattr(PySide6, "__file__", "<unknown>"))
    print("QtCore:", getattr(QtCore, "__file__", "<unknown>"))

    pyside_dir = Path(PySide6.__file__).resolve().parent
    print("PySide6 dir:", pyside_dir)

    print("\n=== Key files ===")
    key_files = [
        pyside_dir / "QtCore.pyd",
        pyside_dir / "plugins" / "platforms" / "qwindows.dll",
    ]
    for fp in key_files:
        print(f"{fp}: {'OK' if fp.exists() else 'MISSING'}")

    print("\n=== PATH preview ===")
    path_items = os.environ.get("PATH", "").split(os.pathsep)
    for item in path_items[:10]:
        print(item)

    print("\nQt 环境检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
