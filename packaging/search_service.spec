# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path, PurePosixPath

from PyInstaller.utils.hooks import collect_all

pyside_datas, pyside_binaries, pyside_hiddenimports = collect_all('PySide6')
shiboken_datas, shiboken_binaries, shiboken_hiddenimports = collect_all('shiboken6')


EXCLUDED_BINARY_SUFFIXES = {
    'qsqlibase.dll',
    'qsqlmimer.dll',
    'qsqloci.dll',
    'qsqlpsql.dll',
    'qtquickshapesdesignhelpersplugin.dll',
}


EXCLUDED_HIDDENIMPORT_PREFIXES = (
    'PySide6.scripts.deploy',
)


def _normalize(path: str) -> str:
    return str(PurePosixPath(path.replace('\\', '/'))).lower()


def _keep_binary(item: tuple[str, str, str]) -> bool:
    src, _, _ = item
    p = _normalize(src)
    return not any(p.endswith(name) for name in EXCLUDED_BINARY_SUFFIXES)


def _keep_hiddenimport(name: str) -> bool:
    return not any(name.startswith(prefix) for prefix in EXCLUDED_HIDDENIMPORT_PREFIXES)


filtered_pyside_binaries = [b for b in pyside_binaries if _keep_binary(b)]
filtered_hiddenimports = [h for h in [*pyside_hiddenimports, *shiboken_hiddenimports] if _keep_hiddenimport(h)]

runtime_hook_file = str(Path(__file__).resolve().parent / 'qt_runtime_hook.py')

a = Analysis(
    ['../search_gui.py'],
    pathex=[],
    binaries=[*filtered_pyside_binaries, *shiboken_binaries],
    datas=[*pyside_datas, *shiboken_datas],
    hiddenimports=filtered_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[runtime_hook_file],
    excludes=[],
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
