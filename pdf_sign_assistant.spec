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

# ── Versión ───────────────────────────────────────────────────────────────────
# Se lee de modules/version.py para no tener el número duplicado en tres
# archivos (app, instalador y workflow leen todos de ahí).
_ns: dict = {}
exec((ROOT / "modules" / "version.py").read_text(encoding="utf-8"), _ns)
APP_VERSION = _ns["__version__"]
APP_NOMBRE  = _ns["APP_NOMBRE"]
APP_AUTOR   = _ns["AUTOR"]
_v = _ns["version_tupla"]()
print(f"[SPEC] {APP_NOMBRE} {APP_VERSION}")

# Recurso VERSIONINFO: sin esto, el .exe aparece sin nombre ni versión en
# las propiedades de Windows, y eso alimenta las alertas de SmartScreen.
_version_file = ROOT / "build" / "version_info.txt"
_version_file.parent.mkdir(parents=True, exist_ok=True)
_version_file.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_v}, prodvers={_v},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040a04b0', [
        StringStruct('CompanyName', '{APP_AUTOR}'),
        StringStruct('FileDescription', '{APP_NOMBRE}'),
        StringStruct('FileVersion', '{APP_VERSION}'),
        StringStruct('InternalName', '{APP_NOMBRE}'),
        StringStruct('LegalCopyright', 'MIT License'),
        StringStruct('OriginalFilename', '{APP_NOMBRE}.exe'),
        StringStruct('ProductName', '{APP_NOMBRE}'),
        StringStruct('ProductVersion', '{APP_VERSION}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1034, 1200])])
  ]
)""", encoding="utf-8")

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
# config.json ya no se versiona (lo escribe el diálogo de Ajustes y puede
# tener credenciales), así que sólo se incluye si existe en el checkout.
# Sin él la app arranca igual: modules.setup.cargar_config() cae en los
# valores por defecto.
datas = [
    *collect_data_files("fitz"),
    *collect_data_files("PyQt6"),
]

for _cfg in ("config.json", "config.example.json"):
    if (ROOT / _cfg).is_file():
        datas.append((str(ROOT / _cfg), "."))

# Icono de la ventana (además del icono del .exe)
if (ROOT / "assets").is_dir():
    datas.append((str(ROOT / "assets" / "icon.png"), "assets"))

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
    # pypdf importa cryptography de forma perezosa, adentro de la función
    # que descifra: el análisis estático de PyInstaller no la ve. Sin este
    # renglón, el .exe sale sin ella y cualquier PDF cifrado con AES —los
    # que sólo restringen imprimir o copiar, que son mayoría— deja de
    # abrirse en la versión empaquetada aunque ande en desarrollo.
    "cryptography",
    "cryptography.hazmat.primitives.ciphers",
    "cryptography.hazmat.primitives.ciphers.algorithms",
    "cryptography.hazmat.primitives.ciphers.modes",
    "cryptography.hazmat.backends.openssl",
    "win32api",
    "win32con",
    "win32print",
    "win32gui",
    "pywintypes",
    "modules.actualizaciones",
    "modules.actualizador",
    "modules.changelog",
    "modules.dispositivos",
    "modules.armado_pdf",
    "modules.documento",
    "modules.errores",
    "modules.escaner_qt",
    "modules.fase1_preview",
    "modules.fase2_print",
    "modules.fase3_scan",
    "modules.fase4_email",
    "modules.fase_guardar",
    "modules.herramienta_escaneo",
    "modules.herramienta_unir",
    "modules.hojas",
    "modules.iconos",
    "modules.imagen_pdf",
    "modules.lista_paginas",
    "modules.navegacion",
    "modules.previa",
    "modules.settings",
    "modules.setup",
    "modules.theme",
    "modules.trabajo",
    "modules.ui",
    "modules.version",
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
    # exchangelib y watchdog ya no se usan; excluirlos evita arrastrar
    # lxml/dnspython/tzlocal al bundle si están en el entorno.
    excludes=[
        "PySimpleGUI", "tkinter", "unittest",
        "exchangelib", "watchdog", "lxml", "dnspython", "tzlocal",
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
    # UPX comprime el binario pero DISPARA falsos positivos de antivirus en
    # ejecutables de PyInstaller. Para distribución pública no vale la pena.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico"),
    version=str(_version_file),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PDF Sign Assistant",
)
