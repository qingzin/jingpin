# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path, PurePosixPath
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


EXCLUDED_PATH_KEYWORDS = (
    '/plugins/sqldrivers/',
    '/qml/qtquick/shapes/designhelpers/',
)


def _normalize(path: str) -> str:
    return str(PurePosixPath(path.replace('\\', '/'))).lower()


def _is_excluded(item: tuple) -> bool:
    parts = [_normalize(part) for part in item if isinstance(part, str)]
    return any(keyword in p for p in parts for keyword in EXCLUDED_PATH_KEYWORDS)


def _collect_ffi_dlls() -> list[tuple[str, str]]:
    dlls: list[tuple[str, str]] = []
    candidates = [
        Path(sys.base_prefix) / 'Library' / 'bin' / 'ffi.dll',
        Path(sys.base_prefix) / 'DLLs' / 'ffi.dll',
    ]
    for p in candidates:
        if p.exists():
            dlls.append((str(p), '.'))
    return dlls


pyside_binaries = collect_dynamic_libs('PySide6')
shiboken_binaries = collect_dynamic_libs('shiboken6')
pyside_datas = collect_data_files('PySide6')

filtered_binaries = [b for b in [*pyside_binaries, *shiboken_binaries] if not _is_excluded(b)]
filtered_datas = [d for d in pyside_datas if not _is_excluded(d)]

runtime_hook_file = str(Path(SPECPATH) / 'qt_runtime_hook.py')

a = Analysis(
    ['../search_gui.py'],
    pathex=[],
    binaries=[*filtered_binaries, *_collect_ffi_dlls()],
    datas=[*filtered_datas],
    hiddenimports=['PySide6', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[runtime_hook_file],
    excludes=['PySide6.scripts.deploy', 'PySide6.scripts.deploy_lib', 'jinja2'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='search_gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
)
