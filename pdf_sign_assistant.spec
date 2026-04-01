# -*- mode: python ; coding: utf-8 -*-
#
# pdf_sign_assistant.spec
# ============================================================
# Archivo de configuración de PyInstaller para PDF Sign Assistant.
#
# Uso:
#   pyinstaller pdf_sign_assistant.spec
#
# Requisitos previos:
#   pip install -r requirements.txt
#
# El ejecutable se genera en: dist/PDF Sign Assistant/
# ============================================================

import sys
import sysconfig
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPEC).parent  # directorio raíz del proyecto

# ── Localizar python3XX.dll ───────────────────────────────────────────────────
# Cuando se trabaja dentro de un venv, sys.exec_prefix apunta al venv y
# la DLL no está ahí — vive en la instalación base de Python.
# sys.base_exec_prefix siempre apunta a la instalación real, dentro o fuera
# de un venv, por eso es el candidato correcto.
_python_dll_name = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
_python_dll_candidates = [
    Path(sys.base_exec_prefix) / _python_dll_name,           # instalación base (venv-safe)
    Path(sys.base_exec_prefix).parent / _python_dll_name,    # un nivel arriba
    Path(sys.exec_prefix) / _python_dll_name,                # fallback: exec_prefix del venv
    Path(sysconfig.get_config_var("BINDIR") or "") / _python_dll_name,
]

_python_dll_path = None
for _c in _python_dll_candidates:
    if _c.is_file():
        _python_dll_path = _c
        print(f"[SPEC] python DLL encontrada: {_python_dll_path}")
        break

if _python_dll_path is None:
    print(
        f"[SPEC] ADVERTENCIA: no se encontró {_python_dll_name} en ninguna "
        f"ubicación conocida.\n"
        f"  base_exec_prefix = {sys.base_exec_prefix}\n"
        f"  exec_prefix      = {sys.exec_prefix}\n"
        f"PyInstaller intentará resolverla automáticamente."
    )

# ── Datos a incluir en el bundle ──────────────────────────────────────────────
datas = [
    (str(ROOT / "config.json"), "."),
    *collect_data_files("fitz"),
    *collect_data_files("PyQt6"),
]

# ── Hidden imports ────────────────────────────────────────────────────────────
hiddenimports = [
    "fitz",
    "fitz.fitz",
    "PyQt6.QtPrintSupport",
    "PyQt6.QtSvg",
    "PyQt6.QtXml",
    "dotenv",
    "reportlab.graphics.barcode.common",
    "reportlab.graphics.barcode.code128",
    "reportlab.graphics.barcode.code93",
    "reportlab.graphics.barcode.usps",
    "reportlab.graphics.barcode.usps4s",
    "reportlab.graphics.barcode.ecc200datamatrix",
    "win32api",
    "win32con",
    "win32print",
    "win32gui",
    "pywintypes",
    "modules.fase1_preview",
    "modules.fase2_print",
    "modules.fase3_scan",
    "modules.fase4_email",
    "modules.fase_guardar",
    "modules.settings",
    "modules.setup",
]

# ── Binarios extra ────────────────────────────────────────────────────────────
binaries = []

if _python_dll_path:
    binaries.append((str(_python_dll_path), "."))

try:
    import win32api
    win32_dir = Path(win32api.__file__).parent
    for dll in win32_dir.glob("*.dll"):
        binaries.append((str(dll), "."))
except Exception:
    pass

# ── Análisis ──────────────────────────────────────────────────────────────────
a = Analysis(
    ["main.py"],
    pathex=[
        str(ROOT),
        sys.base_exec_prefix,   # ← instalación real de Python (venv-safe)
        sys.exec_prefix,
    ],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySimpleGUI", "tkinter", "unittest"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDF Sign Assistant",
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
    # icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PDF Sign Assistant",
)
