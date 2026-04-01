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
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPEC).parent  # directorio raíz del proyecto

# ── Localizar python3XX.dll automáticamente ──────────────────────────────────────────
# PyInstaller a veces no encuentra la DLL cuando Python fue instalado
# solo para el usuario actual (AppData) en lugar de para todos los usuarios.
# Este bloque la busca en las ubicaciones conocidas y la incluye como binario.
_python_dll_name = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
_python_dll_candidates = [
    # Instalación estándar para todos los usuarios
    Path(sys.exec_prefix) / _python_dll_name,
    # Instalación solo para el usuario actual
    Path(sys.exec_prefix).parent / _python_dll_name,
    # Windows\System32 (rara vez, pero posible)
    Path(sysconfig.get_config_var("BINDIR") or sys.exec_prefix) / _python_dll_name,
]

_python_dll_path = None
for _candidate in _python_dll_candidates:
    if _candidate.is_file():
        _python_dll_path = _candidate
        print(f"[SPEC] python DLL encontrada: {_python_dll_path}")
        break

if _python_dll_path is None:
    print(f"[SPEC] ADVERTENCIA: no se encontró {_python_dll_name} — "
          f"PyInstaller intentará resolverla automáticamente.")

# ── Datos a incluir en el bundle ─────────────────────────────────────────────────
datas = [
    # config.json de ejemplo (el usuario lo completa en la carpeta del .exe)
    (str(ROOT / "config.json"),         "."),
    # Datos internos de pymupdf (fitz)
    *collect_data_files("fitz"),
    # Datos internos de PyQt6
    *collect_data_files("PyQt6"),
]

# ── Hidden imports necesarios ────────────────────────────────────────────
hiddenimports = [
    # fitz = pymupdf
    "fitz",
    "fitz.fitz",
    # PyQt6 — módulos que PyInstaller a veces no detecta automáticamente
    "PyQt6.QtPrintSupport",
    "PyQt6.QtSvg",
    "PyQt6.QtXml",
    # python-dotenv
    "dotenv",
    # reportlab internals
    "reportlab.graphics.barcode.common",
    "reportlab.graphics.barcode.code128",
    "reportlab.graphics.barcode.code93",
    "reportlab.graphics.barcode.usps",
    "reportlab.graphics.barcode.usps4s",
    "reportlab.graphics.barcode.ecc200datamatrix",
    # pywin32
    "win32api",
    "win32con",
    "win32print",
    "win32gui",
    "pywintypes",
    # módulos propios
    "modules.fase1_preview",
    "modules.fase2_print",
    "modules.fase3_scan",
    "modules.fase4_email",
    "modules.fase_guardar",
    "modules.settings",
    "modules.setup",
]

# ── Binarios extra ──────────────────────────────────────────────────────────────
binaries = []

# Incluir python3XX.dll si la encontramos
if _python_dll_path:
    binaries.append((str(_python_dll_path), "."))

# Incluir las DLLs de pywin32
try:
    import win32api
    win32_dir = Path(win32api.__file__).parent
    for dll in win32_dir.glob("*.dll"):
        binaries.append((str(dll), "."))
except Exception:
    pass

# ── Análisis ───────────────────────────────────────────────────────────────────
a = Analysis(
    ["main.py"],
    pathex=[
        str(ROOT),
        # Añadir el directorio de Python al path de búsqueda
        # para que PyInstaller encuentre la DLL durante el análisis
        sys.exec_prefix,
    ],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySimpleGUI",
        "tkinter",
        "unittest",
    ],
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
