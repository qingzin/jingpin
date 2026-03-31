# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

a = Analysis(
    ['../builder_gui.py'],
    pathex=[],
    binaries=[*collect_dynamic_libs('PySide6'), *collect_dynamic_libs('shiboken6')],
    datas=[('../config/column_mapping.json', 'config'), *collect_data_files('PySide6')],
    hiddenimports=['yaml', 'PySide6', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
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
