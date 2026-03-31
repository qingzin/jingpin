# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['../builder_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('../config/column_mapping.json', 'config')],
    hiddenimports=['yaml', 'PySide6', 'PySide6.QtCore', 'PySide6.QtWidgets'],
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
