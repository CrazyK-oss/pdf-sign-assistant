import json
import PySimpleGUI as sg
from pathlib import Path


BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
FOLDERS = ["documents", "scans", "temp"]


def setup_directories() -> Path:
    """Crea las carpetas necesarias si no existen. Devuelve el directorio base."""
    for folder in FOLDERS:
        path = BASE_DIR / folder
        path.mkdir(exist_ok=True)
        print(f"[SETUP] Carpeta lista: {path}")
    return BASE_DIR


def load_config() -> dict:
    """Carga y valida config.json. Muestra error amigable si hay problemas."""
    if not CONFIG_PATH.is_file():
        sg.popup_error(
            "No se encontró config.json.\n"
            "Por favor créelo siguiendo el README.md"
        )
        raise SystemExit(1)

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        print("[SETUP] Configuración cargada correctamente.")
        return config
    except json.JSONDecodeError as e:
        sg.popup_error(f"config.json tiene formato inválido:\n{e}")
        raise SystemExit(1)
