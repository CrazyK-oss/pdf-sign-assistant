"""
main.py — Punto de entrada autónomo del PDF Sign Assistant.

Primera vez:  python main.py  →  crea venv, instala dependencias, relanza la app.
Siguientes:   python main.py  →  arranca directo, sin comandos extra.
"""

import sys
import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
VENV_DIR = BASE_DIR / "venv"
REQUIREMENTS = BASE_DIR / "requirements.txt"

# --------------------------------------------------------------------------- #
#  Detectar si ya estamos corriendo DENTRO del venv                           #
# --------------------------------------------------------------------------- #
def _running_in_venv() -> bool:
    return (
        hasattr(sys, "real_prefix")
        or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
    )


# --------------------------------------------------------------------------- #
#  Crear venv si no existe                                                    #
# --------------------------------------------------------------------------- #
def _ensure_venv():
    if not VENV_DIR.exists():
        print("[SETUP] Creando entorno virtual por primera vez...")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
        print("[SETUP] Entorno virtual creado.")


# --------------------------------------------------------------------------- #
#  Ruta al Python/pip dentro del venv                                         #
# --------------------------------------------------------------------------- #
def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _venv_pip() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


# --------------------------------------------------------------------------- #
#  Instalar dependencias                                                      #
# --------------------------------------------------------------------------- #
def _ensure_deps():
    print("[SETUP] Verificando dependencias...")
    subprocess.check_call(
        [str(_venv_pip()), "install", "--quiet", "--upgrade", "pip"],
    )
    subprocess.check_call(
        [str(_venv_pip()), "install", "--quiet", "-r", str(REQUIREMENTS)],
    )
    print("[SETUP] Dependencias listas.")


# --------------------------------------------------------------------------- #
#  Relanzar con el Python del venv                                            #
# --------------------------------------------------------------------------- #
def _relaunch_in_venv():
    print("[SETUP] Relanzando dentro del entorno virtual...\n")
    os.execv(str(_venv_python()), [str(_venv_python())] + sys.argv)


# --------------------------------------------------------------------------- #
#  Bootstrap: sólo corre si NO estamos dentro del venv                       #
# --------------------------------------------------------------------------- #
if not _running_in_venv():
    _ensure_venv()
    _ensure_deps()
    _relaunch_in_venv()


# --------------------------------------------------------------------------- #
#  A partir de aquí el código corre SIEMPRE dentro del venv                  #
# --------------------------------------------------------------------------- #
import PySimpleGUI as sg  # noqa: E402  (importación después del bootstrap)
from modules.setup import setup_directories, load_config
from modules.fase1_preview import seleccionar_paginas
from modules.fase2_print import imprimir_paginas
from modules.fase3_scan import escanear_y_reemplazar
from modules.fase4_email import enviar_documento


def main():
    base_dir = setup_directories()
    config = load_config()

    sg.theme("LightGreen2")

    while True:
        docs_dir = base_dir / "documents"
        pdf_files = list(docs_dir.glob("*.pdf"))

        if not pdf_files:
            sg.popup_error(
                f"No se encontraron PDFs en:\n{docs_dir}\n"
                "Por favor coloque al menos un PDF en la carpeta 'documents'."
            )
            break

        # --- PANTALLA DE INICIO: Selección de documento ---
        layout_inicio = [
            [sg.Text("Seleccione el documento a firmar:", font=("Helvetica", 16, "bold"))],
            [
                sg.Listbox(
                    values=[f.name for f in pdf_files],
                    size=(50, min(10, len(pdf_files))),
                    key="-DOC-",
                    font=("Helvetica", 13),
                    enable_events=True,
                )
            ],
            [
                sg.Button("SALIR", size=(12, 1), button_color=("white", "#dc3545")),
                sg.Button(
                    "CONTINUAR",
                    size=(12, 1),
                    button_color=("white", "#007BFF"),
                    disabled=True,
                    key="-BTN-CONTINUAR-",
                ),
            ],
        ]

        win_inicio = sg.Window(
            "Asistente de Firmas Legales",
            layout_inicio,
            element_justification="c",
            finalize=True,
        )

        doc_seleccionado = None
        while True:
            ev, vals = win_inicio.read()
            if ev in (sg.WIN_CLOSED, "SALIR"):
                win_inicio.close()
                return
            if ev == "-DOC-" and vals["-DOC-"]:
                doc_seleccionado = docs_dir / vals["-DOC-"][0]
                win_inicio["-BTN-CONTINUAR-"].update(disabled=False)
            if ev == "-BTN-CONTINUAR-" and doc_seleccionado:
                break
        win_inicio.close()

        # --- EJECUTAR FASES EN SECUENCIA ---
        try:
            # FASE 1: Vista previa y selección de páginas
            paginas = seleccionar_paginas(doc_seleccionado)
            if paginas is None:
                continue  # Usuario canceló, volver a inicio

            # FASE 2: Imprimir páginas seleccionadas
            temp_print = base_dir / "temp" / "paginas_a_imprimir.pdf"
            if not imprimir_paginas(doc_seleccionado, paginas, temp_print):
                continue

            # FASE 3: Escanear y reemplazar páginas en el PDF original
            scans_dir = base_dir / "scans"
            temp_firmado = base_dir / "temp" / "documento_firmado.pdf"
            if not escanear_y_reemplazar(doc_seleccionado, paginas, scans_dir, temp_firmado):
                continue

            # FASE 4: Resumen y envío por email
            enviar_documento(temp_firmado, config, paginas, doc_seleccionado.name)

        except Exception as e:
            sg.popup_error(f"Error inesperado:\n{e}")
            print(f"[ERROR MAIN] {e}")


if __name__ == "__main__":
    main()
