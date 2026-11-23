# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build for ASCEND Flight Control (macOS .app, Windows .exe, Raspberry Pi / Linux).
#
#     python -m PyInstaller --clean --noconfirm "ASCEND Flight Control.spec"
#
# Needs tools/bossac (tools/bossac.exe on Windows) for the RC Configurator tab, as
# the release workflow stages it. Check the result with:  <app> --self-test
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)
APP = ROOT / "ascend_flight_control"
sys.path.insert(0, str(APP))
from version import APP_VERSION  # noqa: E402

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
NAME = "ASCEND Flight Control"

esptool_datas, esptool_binaries, esptool_hiddenimports = collect_all("esptool")
bossac = ROOT / "tools" / ("bossac.exe" if IS_WIN else "bossac")

datas = esptool_datas + [
    (str(ROOT / "assets" / "altitude_unknown_icon.png"), "assets"),
    (str(APP / "param_metadata" / "ArduPlane.json"), "param_metadata"),
]
binaries = esptool_binaries + [(str(bossac), "tools")]
if IS_MAC:
    binaries.append((str(APP / "native" / "libascend_pinch.dylib"), "native"))

hiddenimports = esptool_hiddenimports + collect_submodules("tkintermapview") + [
    # mavutil imports its message definitions at run time, so PyInstaller cannot see them.
    # The default dialect is "all" (it includes ardupilotmega); MAVLINK20=1 selects v20.
    "pymavlink.dialects.v20.all",
    "pymavlink.dialects.v10.all",
]

a = Analysis(
    [str(APP / "ascend_flight_control.py")],
    pathex=[str(APP), str(ROOT)],  # ROOT holds the RC Configurator (fram_gui_models.py)
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
icon = str(ROOT / "assets" / ("altitude_unknown_icon.icns" if IS_MAC else "altitude_unknown_icon.png"))

if IS_MAC:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, debug=False, strip=False, upx=False,
              console=False, argv_emulation=False, target_arch=None, codesign_identity=None,
              entitlements_file=None)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        icon=icon,
        bundle_identifier="com.altitudeunknown.ascendflightcontrol",
        info_plist={
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
        },
    )
else:
    # One self-contained file for Windows and Raspberry Pi.
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              name="ASCEND-Flight-Control" if IS_WIN else NAME,
              debug=False, strip=False, upx=False, console=False, icon=icon)
