# hwinfo_monitor.spec
import os
from PyInstaller.utils.hooks import collect_all

_stress_dll = os.path.join('core', 'stress_native.dll')
_stress_c   = os.path.join('core', 'stress_native.c')
_extra_binaries = [(_stress_dll, 'core')] if os.path.exists(_stress_dll) else []
_extra_datas    = [(_stress_c,   'core')] if os.path.exists(_stress_c)   else []

# Properly collect numpy — hiddenimports alone misses the compiled .pyd extensions
numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all('numpy')

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=_extra_binaries + numpy_binaries,
    datas=[
        ('dist\\LHMBridge', 'LHMBridge'),
        ('stress_worker.py', '.'),
        ('core', 'core'),
    ] + _extra_datas + numpy_datas,
    hiddenimports=[
        'wmi', 'psutil', 'tkinter', 'tkinter.font',
        'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFilter',
        'PIL._imaging', 'PIL._tkinter_finder',
        'numpy', 'numpy.core', 'numpy.core._multiarray_umath',
        'numpy.core.multiarray', 'numpy.linalg',
        'numpy.linalg._umath_linalg', 'numpy.random',
        'threadpoolctl', 'ctypes', 'ctypes.wintypes',
    ] + numpy_hiddenimports,
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
