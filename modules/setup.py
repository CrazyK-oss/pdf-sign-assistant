"""
modules/setup.py
============================================================
Utilidades de arranque: creación de carpetas y carga de config.
Compatible con ejecución directa (python main.py) y con
binarios generados por PyInstaller (bundle congelado).

NOTA: no usa PySimpleGUI — los errores se muestran con PyQt6
para mantener coherencia visual y evitar dependencias extra.
"""

import json
import sys
from pathlib import Path


# ── Directorio base ────────────────────────────────────────────────────────────────
def get_base_dir() -> Path:
    """
    Devuelve el directorio base de la aplicación.
    - Cuando se ejecuta con PyInstaller (frozen): carpeta del .exe
    - Cuando se ejecuta como script normal: carpeta del proyecto
    """
    if getattr(sys, "frozen", False):
        # Ejecutable PyInstaller: sys.executable es la ruta al .exe
        return Path(sys.executable).parent
    # Script normal: dos niveles arriba de este archivo (modules/setup.py)
    return Path(__file__).parent.parent


BASE_DIR    = get_base_dir()
CONFIG_PATH = BASE_DIR / "config.json"
FOLDERS     = ["pdfs_trabajo", "pdfs_firmados"]


def setup_directories() -> Path:
    """Crea las carpetas necesarias si no existen. Devuelve el directorio base."""
    for folder in FOLDERS:
        path = BASE_DIR / folder
        path.mkdir(exist_ok=True)
        print(f"[SETUP] Carpeta lista: {path}")
    return BASE_DIR


def load_config() -> dict:
    """
    Carga y valida config.json.
    Muestra error amigable con QMessageBox si hay problemas.
    """
    if not CONFIG_PATH.is_file():
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            import sys as _sys
            _app = QApplication.instance() or QApplication(_sys.argv)
            QMessageBox.critical(
                None,
                "Configuración no encontrada",
                f"No se encontró config.json en:\n{BASE_DIR}\n\n"
                "Por favor creá el archivo siguiendo el README.md"
            )
        except Exception:
            print(f"[ERROR] No se encontró config.json en: {BASE_DIR}")
        raise SystemExit(1)

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        print("[SETUP] Configuración cargada correctamente.")
        return config
    except json.JSONDecodeError as e:
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            import sys as _sys
            _app = QApplication.instance() or QApplication(_sys.argv)
            QMessageBox.critical(
                None,
                "Error de configuración",
                f"config.json tiene formato inválido:\n{e}"
            )
        except Exception:
            print(f"[ERROR] config.json inválido: {e}")
        raise SystemExit(1)
