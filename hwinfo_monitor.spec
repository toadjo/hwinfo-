# hwinfo_monitor.spec
block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('dist\\LHMBridge', 'LHMBridge'),
        ('stress_worker.py', '.'),
        ('core', 'core'),
    ],
    hiddenimports=[
        'wmi', 'psutil', 'tkinter', 'tkinter.font',
        'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFilter',
        'PIL._imaging', 'PIL._tkinter_finder',
        'numpy', 'numpy.core', 'numpy.core._multiarray_umath',
        'numpy.core.multiarray', 'numpy.linalg',
        'numpy.linalg._umath_linalg', 'numpy.random',
        'threadpoolctl', 'ctypes', 'ctypes.wintypes',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='HWInfoMonitor',
    debug=False,
    strip=False,
    upx=True,
    console=False,
    uac_admin=True,
    icon=None,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name='HWInfoMonitor',
)
