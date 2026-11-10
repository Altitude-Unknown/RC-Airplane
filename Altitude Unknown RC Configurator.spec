# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

esptool_datas, esptool_binaries, esptool_hiddenimports = collect_all('esptool')


a = Analysis(
    ['fram_gui_models.py'],
    pathex=[],
    binaries=esptool_binaries + [('tools/bossac', 'tools')],
    datas=esptool_datas + [('assets/altitude_unknown_icon.png', 'assets')],
    hiddenimports=esptool_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Altitude Unknown RC Configurator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Altitude Unknown RC Configurator',
)
app = BUNDLE(
    coll,
    name='Altitude Unknown RC Configurator.app',
    icon='assets/altitude_unknown_icon.icns',
    bundle_identifier='com.altitudeunknown.rcconfigurator',
)
