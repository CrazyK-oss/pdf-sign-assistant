import platform
import subprocess
from pathlib import Path
import PySimpleGUI as sg
from PyPDF2 import PdfReader, PdfWriter


def _exportar_paginas(ruta_original: Path, paginas: list[int], destino: Path) -> bool:
    """Extrae las páginas seleccionadas del PDF original y las guarda en un archivo temporal."""
    try:
        reader = PdfReader(ruta_original)
        writer = PdfWriter()
        for idx in paginas:
            writer.add_page(reader.pages[idx])
        with open(destino, "wb") as f:
            writer.write(f)
        print(f"[FASE 2] PDF de impresión generado: {destino}")
        return True
    except Exception as e:
        sg.popup_error(f"Error al preparar páginas para imprimir:\n{e}")
        print(f"[ERROR fase2 export] {e}")
        return False


def _enviar_a_impresora(ruta_pdf: Path) -> bool:
    """Envía el PDF a la impresora predeterminada del sistema."""
    sistema = platform.system()
    try:
        if sistema == "Windows":
            # En Windows, 'start /wait' abre el PDF con el visor predeterminado e imprime
            subprocess.run(
                ["powershell", "-Command", f'Start-Process -FilePath "{ruta_pdf}" -Verb Print -Wait'],
                check=True,
            )
        elif sistema == "Linux":
            subprocess.run(["lp", str(ruta_pdf)], check=True)
        elif sistema == "Darwin":  # macOS
            subprocess.run(["lpr", str(ruta_pdf)], check=True)
        else:
            sg.popup_error(f"Sistema operativo no soportado para impresión: {sistema}")
            return False
        print(f"[FASE 2] Enviado a impresora: {ruta_pdf}")
        return True
    except subprocess.CalledProcessError as e:
        sg.popup_error(f"Error al enviar a la impresora:\n{e}")
        print(f"[ERROR fase2 print] {e}")
        return False


def imprimir_paginas(ruta_pdf: Path, paginas: list[int], temp_path: Path) -> bool:
    """
    Extrae las páginas seleccionadas, las envía a imprimir y espera confirmación
    física del usuario antes de continuar.

    Args:
        ruta_pdf:   Path al PDF original.
        paginas:    Lista de índices 0-based de páginas a imprimir.
        temp_path:  Path donde guardar el PDF temporal de impresión.

    Returns:
        True si el usuario confirmó que imprimió, False si canceló.
    """
    nums_display = ", ".join(str(p + 1) for p in paginas)

    # Exportar páginas a archivo temporal
    if not _exportar_paginas(ruta_pdf, paginas, temp_path):
        return False

    # Enviar a impresora
    if not _enviar_a_impresora(temp_path):
        return False

    # Esperar confirmación física del usuario
    layout = [
        [sg.Text("🖨️", font=("Helvetica", 48), justification="c")],
        [
            sg.Text(
                "Imprimiendo páginas...",
                font=("Helvetica", 16, "bold"),
                justification="c",
            )
        ],
        [
            sg.Text(
                f"Páginas enviadas a imprimir:  {nums_display}",
                font=("Helvetica", 13),
                justification="c",
            )
        ],
        [sg.HorizontalSeparator(pad=(0, 20))],
        [
            sg.Text(
                "Cuando salgan las páginas de la impresora:\n"
                "  1. Fírmelas donde corresponde\n"
                "  2. Colóquelas en el escáner\n"
                "  3. Presione el botón de abajo",
                font=("Helvetica", 13),
                justification="l",
            )
        ],
        [sg.VPush()],
        [
            sg.Button(
                "CANCELAR",
                size=(12, 1),
                button_color=("white", "#dc3545"),
                font=("Helvetica", 11),
            ),
            sg.Button(
                "YA FIRMÉ, CONTINUAR AL ESCANEO →",
                size=(28, 2),
                button_color=("white", "#28a745"),
                font=("Helvetica", 12, "bold"),
                key="-CONTINUAR-",
            ),
        ],
    ]

    ventana = sg.Window(
        "Esperando firma física",
        layout,
        element_justification="c",
        size=(520, 380),
        finalize=True,
    )

    while True:
        ev, _ = ventana.read()
        if ev in (sg.WIN_CLOSED, "CANCELAR"):
            ventana.close()
            return False
        if ev == "-CONTINUAR-":
            ventana.close()
            return True
