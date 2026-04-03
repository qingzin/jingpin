from __future__ import annotations

import os
import sys
from pathlib import Path


def _add_path_front(path: Path) -> None:
    if not path.exists():
        return
    current = os.environ.get("PATH", "")
    p = str(path)
    if p.lower() in current.lower():
        return
    os.environ["PATH"] = p + (os.pathsep + current if current else "")


def _add_dll_dir(path: Path) -> None:
    if hasattr(os, "add_dll_directory") and path.exists():
        try:
            os.add_dll_directory(str(path))
        except OSError:
            # 某些目录在受限环境下可能无法注册，忽略并继续。
            pass


def configure_qt_runtime() -> None:
    if os.name != "nt":
        return

    exe_dir = Path(sys.executable).resolve().parent
    base_dir = Path(getattr(sys, "_MEIPASS", exe_dir))

    internal_dir = exe_dir / "_internal"
    candidates = [
        base_dir,
        base_dir / "PySide6",
        base_dir / "shiboken6",
        exe_dir,
        exe_dir / "PySide6",
        exe_dir / "shiboken6",
        internal_dir,
        internal_dir / "PySide6",
        internal_dir / "shiboken6",
        Path(sys.base_prefix) / "DLLs",
        Path(sys.base_prefix) / "Library" / "bin",
    ]

    for p in candidates:
        _add_path_front(p)
        _add_dll_dir(p)

    plugin_dir = base_dir / "PySide6" / "plugins"
    qml_dir = base_dir / "PySide6" / "qml"
    if plugin_dir.exists():
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugin_dir))
    if qml_dir.exists():
        os.environ.setdefault("QML2_IMPORT_PATH", str(qml_dir))
