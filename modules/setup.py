"""
modules/setup.py
============================================================
Utilidades de arranque: rutas de la app, carpetas de trabajo y
lectura/escritura de config.json.

Dónde escribe la app
--------------------
Antes todo (config, logs, PDFs) se guardaba JUNTO AL .exe. Eso funciona
mientras la app vive en una carpeta del usuario, pero se rompe apenas se
instala en `C:\\Program Files`: esa ruta es de sólo lectura sin permisos
de administrador, así que fallarían los ajustes, el log y el guardado.

Reparto estándar de Windows:
  - Config y logs → %LOCALAPPDATA%\\PDF Sign Assistant
  - Copias de trabajo → %LOCALAPPDATA%\\PDF Sign Assistant\\pdfs_trabajo
  - Documentos firmados → Documentos\\PDF Sign Assistant  (los busca el
    usuario, así que van donde sabe encontrarlos)

Modo portable
-------------
Si existe un archivo `portable.txt` junto al ejecutable, se vuelve al
comportamiento anterior y todo queda al lado de la app: útil para
llevarla en un pendrive.

Migración
---------
Si se encuentran datos de una versión anterior junto al ejecutable, se
mueven a la ubicación nueva la primera vez. Nadie pierde sus documentos.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import shutil
import sys
from pathlib import Path

APP_NOMBRE = "PDF Sign Assistant"


# ── Directorio base (recursos que viajan con la app) ──────────────────────────
def get_base_dir() -> Path:
    """
    Devuelve el directorio base de la aplicación.
    - Con PyInstaller (frozen): carpeta del .exe
    - Como script normal: carpeta del proyecto

    Sirve para LEER recursos empaquetados. Para ESCRIBIR, usar
    directorio_datos() / directorio_documentos().
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def es_portable() -> bool:
    """True si hay un portable.txt junto a la app (todo queda al lado)."""
    try:
        return (get_base_dir() / "portable.txt").is_file()
    except OSError:
        return False


def _carpeta_documentos_usuario() -> Path:
    """Carpeta 'Documentos' real del usuario.

    En Windows se consulta a la API (SHGetKnownFolderPath) en vez de
    asumir ~/Documents: la carpeta puede estar redirigida a OneDrive o a
    una unidad de red, y ahí el atajo ingenuo crearía una carpeta suelta
    en el perfil que el usuario nunca encontraría.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            import ctypes.wintypes

            # FOLDERID_Documents
            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", ctypes.c_uint32),
                    ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            folderid = GUID(
                0xFDD39AD0, 0x238F, 0x46AF,
                (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
            )
            ruta = ctypes.c_wchar_p()
            resultado = ctypes.windll.shell32.SHGetKnownFolderPath(  # type: ignore[attr-defined]
                ctypes.byref(folderid), 0, None, ctypes.byref(ruta))
            if resultado == 0 and ruta.value:
                destino = Path(ruta.value)
                ctypes.windll.ole32.CoTaskMemFree(ruta)  # type: ignore[attr-defined]
                return destino
        except Exception:
            pass
    return Path.home() / "Documents"


def directorio_datos() -> Path:
    """Carpeta para config, logs y copias de trabajo (no visible al usuario)."""
    if es_portable():
        return get_base_dir()

    if sys.platform == "win32":
        raiz = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        raiz = Path.home() / "Library" / "Application Support"
    else:
        raiz = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(raiz) / APP_NOMBRE


def directorio_documentos() -> Path:
    """Carpeta donde quedan los PDFs firmados (visible para el usuario)."""
    if es_portable():
        return get_base_dir() / "pdfs_firmados"
    return _carpeta_documentos_usuario() / APP_NOMBRE


BASE_DIR = get_base_dir()
DIR_DATOS = directorio_datos()

CONFIG_PATH     = DIR_DATOS / "config.json"
CARPETA_TRABAJO = DIR_DATOS / "pdfs_trabajo"
CARPETA_LOGS    = DIR_DATOS / "logs"
CARPETA_FIRMADO = directorio_documentos()
FOLDERS = (CARPETA_TRABAJO, CARPETA_FIRMADO)

# Valores por defecto de la configuración
CONFIG_DEFAULT: dict = {
    "email_user": "",
    "email_password": "",
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "tema": "light",
}


def migrar_datos_antiguos(candidatos=None) -> list[str]:
    """Mueve datos de versiones anteriores (guardados junto al .exe) a las
    ubicaciones nuevas. Devuelve una lista de lo migrado, para el log.

    Nunca pisa datos nuevos con viejos: si el destino ya existe, sólo se
    trasladan los elementos que allá todavía no están. Si algo falla, se
    sigue de largo — la app tiene que arrancar igual.

    `candidatos` es una secuencia de pares (origen, destino); por defecto
    usa las rutas reales de la app. Se puede pasar explícitamente para
    poder testear la migración sin tocar el sistema del usuario.
    """
    if candidatos is None:
        if es_portable():
            return []
        candidatos = (
            (BASE_DIR / "config.json",    CONFIG_PATH),
            (BASE_DIR / "pdfs_trabajo",   CARPETA_TRABAJO),
            (BASE_DIR / "logs",           CARPETA_LOGS),
            (BASE_DIR / "pdfs_firmados",  CARPETA_FIRMADO),
        )

    movidos: list[str] = []
    for origen, destino in candidatos:
        try:
            if not origen.exists() or origen.resolve() == destino.resolve():
                continue

            if not destino.exists():
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(origen), str(destino))
                movidos.append(f"{origen.name} → {destino}")
                continue

            # El destino ya existe: movemos el contenido pieza por pieza
            # sin pisar nada que ya esté del otro lado.
            if origen.is_dir() and destino.is_dir():
                for hijo in list(origen.iterdir()):
                    objetivo = destino / hijo.name
                    if objetivo.exists():
                        continue
                    shutil.move(str(hijo), str(objetivo))
                    movidos.append(f"{hijo.name} → {destino}")
                try:
                    origen.rmdir()      # sólo si quedó vacía
                except OSError:
                    pass
        except Exception:                            # noqa: BLE001
            continue
    return movidos


def setup_directories() -> Path:
    """Migra datos de versiones anteriores y crea las carpetas necesarias.

    La migración va PRIMERO: si creáramos las carpetas antes, el destino
    ya existiría y la migración se saltearía siempre, dejando los datos
    viejos huérfanos junto al ejecutable.
    """
    migrados = migrar_datos_antiguos()

    for path in FOLDERS:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    if migrados:
        logging.getLogger(__name__).info(
            "Datos migrados a las ubicaciones nuevas: %s", "; ".join(migrados))
    return BASE_DIR


# ── Configuración ─────────────────────────────────────────────────────────────
def cargar_config(ruta: Path | None = None) -> dict:
    """Lee config.json y lo fusiona con los valores por defecto.

    Nunca lanza: si el archivo no existe o está corrupto devuelve los
    valores por defecto, para que la app siempre pueda arrancar.
    """
    ruta = ruta or CONFIG_PATH
    config = dict(CONFIG_DEFAULT)
    try:
        if ruta.is_file():
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
            if isinstance(datos, dict):
                config.update(datos)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[SETUP] config.json no se pudo leer ({e}); se usan valores por defecto.")
    return config


def guardar_config(config: dict, ruta: Path | None = None) -> None:
    """Escribe config.json de forma atómica (temporal + reemplazo).

    Evita dejar el archivo a medio escribir si la app se cierra o falla
    en mitad del guardado.
    """
    ruta = ruta or CONFIG_PATH
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    tmp.replace(ruta)


# Alias retrocompatible con el nombre anterior
def load_config() -> dict:
    return cargar_config()


# ── Logging ───────────────────────────────────────────────────────────────────
def configurar_logging(nivel: int = logging.INFO) -> Path:
    """Deja el log en logs/pdf_sign_assistant.log, con rotación.

    Es la única forma de ver qué pasó en la máquina del usuario: el .exe
    se compila con `console=False`, así que todo lo que se imprimía por
    consola (incluidos los traceback de las fases) simplemente se perdía.

    Rota a los 512 KB y conserva 3 archivos: no crece sin control en una
    PC que queda encendida meses.
    """
    CARPETA_LOGS.mkdir(parents=True, exist_ok=True)
    archivo = CARPETA_LOGS / "pdf_sign_assistant.log"

    raiz = logging.getLogger()
    raiz.setLevel(nivel)

    # Evita duplicar handlers si se llama dos veces
    for h in list(raiz.handlers):
        if getattr(h, "_psa", False):
            return archivo

    formato = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s")

    handler = logging.handlers.RotatingFileHandler(
        archivo, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(formato)
    handler._psa = True                              # type: ignore[attr-defined]
    raiz.addHandler(handler)

    # En modo script también conviene verlo por consola
    if not getattr(sys, "frozen", False):
        consola = logging.StreamHandler()
        consola.setFormatter(formato)
        consola._psa = True                          # type: ignore[attr-defined]
        raiz.addHandler(consola)

    return archivo


def limpiar_trabajos_huerfanos(dias: int = 7) -> int:
    """Borra copias viejas de pdfs_trabajo/ que quedaron de sesiones caídas.

    Si la app se cierra de golpe (o se corta la luz) la copia de trabajo
    queda ahí para siempre. Devuelve cuántas borró.
    """
    import time
    limite = time.time() - dias * 86400
    borrados = 0
    try:
        for pdf in CARPETA_TRABAJO.glob("*.pdf"):
            try:
                if pdf.stat().st_mtime < limite:
                    pdf.unlink()
                    borrados += 1
            except OSError:
                continue
    except OSError:
        pass
    return borrados
