# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

pyside6_datas, pyside6_binaries, pyside6_hiddenimports = collect_all('PySide6')
shiboken_datas, shiboken_binaries, shiboken_hiddenimports = collect_all('shiboken6')

a = Analysis(
    ['../builder_gui.py'],
    pathex=[],
    binaries=[*pyside6_binaries, *shiboken_binaries],
    datas=[('../config/column_mapping.json', 'config'), *pyside6_datas, *shiboken_datas],
    hiddenimports=['yaml', 'PySide6', 'PySide6.QtCore', 'PySide6.QtWidgets', *pyside6_hiddenimports, *shiboken_hiddenimports],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    name='builder_tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
)
