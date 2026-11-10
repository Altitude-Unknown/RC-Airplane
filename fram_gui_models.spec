# -*- mode: python ; coding: utf-8 -*-
block_cipher = None

a = Analysis(['fram_gui_models.py'],
             pathex=['.'],
             binaries=[],
             datas=[('assets/altitude_unknown_icon.png', 'assets')],
             hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='AltitudeUnknownRCConfigurator',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=False)

coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               name='AltitudeUnknownRCConfigurator')

# Notes: to build one-file exe, prefer the CLI:
#   pyinstaller --onefile --windowed fram_gui_models.py
# Or to use this spec (onedir):
#   pyinstaller fram_gui_models.spec
