from __future__ import annotations

import platform
import site
import subprocess
import sys
from pathlib import Path


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    _print_header("Python 环境")
    print(f"executable: {sys.executable}")
    print(f"version: {sys.version.split()[0]}")
    print(f"arch: {platform.architecture()[0]} / machine={platform.machine()}")

    _print_header("site-packages")
    for p in site.getsitepackages():
        print(p)

    _print_header("pip show PySide6")
    r = subprocess.run([sys.executable, "-m", "pip", "show", "PySide6"], capture_output=True, text=True)
    print(r.stdout.strip() or "(no output)")
    if r.returncode != 0:
        print(r.stderr.strip())

    _print_header("检查 PySide6 关键文件")
    sp = [Path(p) for p in site.getsitepackages()]
    found = False
    for base in sp:
        pyside = base / "PySide6"
        if pyside.exists():
            found = True
            print(f"PySide6 path: {pyside}")
            for name in ["QtCore.pyd", "Qt6Core.dll", "shiboken6.abi3.dll"]:
                fp = pyside / name
                print(f"  {'OK ' if fp.exists() else 'MISS'} {fp}")
    if not found:
        print("未找到 PySide6 目录。")

    _print_header("尝试导入")
    try:
        import PySide6  # noqa: F401
        from PySide6 import QtCore

        print("PySide6 导入成功")
        print(f"QtCore: {QtCore.__file__}")
        print(f"Qt version: {QtCore.qVersion()}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"PySide6 导入失败: {exc}")
        print("\n建议排查：")
        print("1) 确认 Python 与 PySide6 位数一致（建议 64 位）。")
        print("2) 安装/修复 Microsoft Visual C++ 2015-2022 Redistributable (x64)。")
        print("3) 用当前解释器重装：python -m pip uninstall -y PySide6 shiboken6 && python -m pip install --no-cache-dir PySide6")
        print("4) 避免系统 PATH 指向其他 Qt/PySide 目录，重开终端后再试。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
