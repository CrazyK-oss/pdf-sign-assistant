"""
modules/setup.py
============================================================
Utilidades de arranque: rutas base, carpetas de trabajo y
lectura/escritura de config.json.

Compatible con ejecución directa (python main.py) y con binarios
generados por PyInstaller (bundle congelado).

Acá vive la ÚNICA implementación de carga/guardado de configuración:
antes main.py y settings.py tenían cada uno la suya.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


# ── Directorio base ───────────────────────────────────────────────────────────
def get_base_dir() -> Path:
    """
    Devuelve el directorio base de la aplicación.
    - Con PyInstaller (frozen): carpeta del .exe
    - Como script normal: carpeta del proyecto
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


BASE_DIR = get_base_dir()
CONFIG_PATH = BASE_DIR / "config.json"

CARPETA_TRABAJO = BASE_DIR / "pdfs_trabajo"
CARPETA_FIRMADO = BASE_DIR / "pdfs_firmados"
FOLDERS = (CARPETA_TRABAJO, CARPETA_FIRMADO)

# Valores por defecto de la configuración
CONFIG_DEFAULT: dict = {
    "email_user": "",
    "email_password": "",
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "tema": "light",
}


def setup_directories() -> Path:
    """Crea las carpetas necesarias si no existen. Devuelve el directorio base."""
    for path in FOLDERS:
        path.mkdir(parents=True, exist_ok=True)
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
