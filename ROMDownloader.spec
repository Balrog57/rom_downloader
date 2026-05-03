# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


datas = [
    ('assets', 'assets'),
    ('dat', 'dat'),
    ('db', 'db'),
    ('VERSION', '.'),
]
datas += collect_data_files('tkinterdnd2')

binaries = []
binaries += collect_dynamic_libs('tkinterdnd2')

hiddenimports = []


def safe_collect_submodules(package_name):
    try:
        return collect_submodules(package_name)
    except Exception:
        return []


for package in (
    'py7zr',
    'rarfile',
    'tkinterdnd2',
    'pybcj',
    'pyppmd',
    'pyzstd',
    'pycryptodomex',
    'multivolumefile',
    'inflate64',
    'brotli',
    'backports.zstd',
):
    hiddenimports += safe_collect_submodules(package)


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['libtorrent'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ROMDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
