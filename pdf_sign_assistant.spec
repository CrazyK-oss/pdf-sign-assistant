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
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPEC).parent  # directorio raíz del proyecto

# ── Datos a incluir en el bundle ───────────────────────────────────────────
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

# ── Binarios extra (pywin32 DLLs) ────────────────────────────────────────
binaries = []

# Intentar incluir las DLLs de pywin32 automáticamente si están disponibles
try:
    import win32api
    import os
    win32_dir = Path(win32api.__file__).parent
    for dll in win32_dir.glob("*.dll"):
        binaries.append((str(dll), "."))
except Exception:
    pass

# ── Análisis ───────────────────────────────────────────────────────────────────
a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Excluir PySimpleGUI (no se usa más)
        "PySimpleGUI",
        # Excluir módulos innecesarios para reducir tamaño
        "tkinter",
        "unittest",
        "email.headerregistry",
        "xml.etree.ElementTree",
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
    console=False,       # Sin ventana de consola (app GUI)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",  # Descomentá cuando tengas un .ico
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
