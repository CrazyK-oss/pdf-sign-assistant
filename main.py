import PySimpleGUI as sg
from modules.setup import setup_directories, load_config
from modules.fase1_preview import seleccionar_paginas
from modules.fase2_print import imprimir_paginas
from modules.fase3_scan import escanear_y_reemplazar
from modules.fase4_email import enviar_documento
from pathlib import Path


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
