from pathlib import Path
from io import BytesIO
import PySimpleGUI as sg
from PyPDF2 import PdfReader
from pdf2image import convert_from_path


COLS_POR_FILA = 4
DPI_PREVIEW = 120  # Balance entre calidad visual y velocidad de carga
THUMB_MAX_HEIGHT = 280  # px máximo por miniatura


def _pdf_a_bytes(imagenes_pil: list) -> list[bytes]:
    """Convierte lista de PIL Images a bytes JPEG para PySimpleGUI."""
    resultado = []
    for img in imagenes_pil:
        # Redimensionar manteniendo aspect ratio
        w, h = img.size
        if h > THUMB_MAX_HEIGHT:
            ratio = THUMB_MAX_HEIGHT / h
            img = img.resize((int(w * ratio), THUMB_MAX_HEIGHT))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        resultado.append(buf.getvalue())
    return resultado


def _construir_grid(imagenes_bytes: list[bytes]) -> list:
    """Construye el grid de miniaturas como elementos de PySimpleGUI."""
    total = len(imagenes_bytes)
    filas = []
    for fila_idx in range(0, total, COLS_POR_FILA):
        fila_elems = []
        for i in range(fila_idx, min(fila_idx + COLS_POR_FILA, total)):
            fila_elems.append(
                sg.Column(
                    [
                        [
                            sg.Button(
                                image_data=imagenes_bytes[i],
                                key=f"-PAG-{i}-",
                                button_color=("white", "#e9ecef"),
                                border_width=3,
                                pad=(6, 6),
                            )
                        ],
                        [
                            sg.Text(
                                f"Página {i + 1}",
                                font=("Helvetica", 10),
                                justification="c",
                                key=f"-LABEL-{i}-",
                            )
                        ],
                    ],
                    element_justification="c",
                )
            )
        filas.append(fila_elems)
    return filas


def seleccionar_paginas(ruta_pdf: Path) -> list[int] | None:
    """
    Muestra vista previa de todas las páginas del PDF y permite al usuario
    seleccionar cuáles necesita imprimir y firmar físicamente.

    Args:
        ruta_pdf: Path al archivo PDF original.

    Returns:
        Lista de índices 0-based de páginas seleccionadas, o None si el usuario cancela.

    Requiere:
        - poppler instalado y en PATH (para pdf2image)
          Windows: https://github.com/oschwartz10612/poppler-windows/releases/
          Linux:   sudo apt-get install poppler-utils
    """
    if not ruta_pdf.is_file():
        sg.popup_error(f"Archivo no encontrado:\n{ruta_pdf}")
        return None

    try:
        reader = PdfReader(ruta_pdf)
        total = len(reader.pages)
        if total == 0:
            sg.popup_error("El PDF no contiene páginas.")
            return None

        # Generar miniaturas (operación más lenta, hacerla una sola vez)
        imagenes_pil = convert_from_path(
            str(ruta_pdf), dpi=DPI_PREVIEW, fmt="jpeg"
        )
        imagenes_bytes = _pdf_a_bytes(imagenes_pil)
        grid_filas = _construir_grid(imagenes_bytes)

        layout = [
            [
                sg.Text(
                    "Toque las páginas que necesita IMPRIMIR y FIRMAR:",
                    font=("Helvetica", 15, "bold"),
                )
            ],
            [
                sg.Text(
                    f"{ruta_pdf.name}  •  {total} páginas",
                    font=("Helvetica", 10),
                    text_color="gray",
                )
            ],
            [
                sg.Column(
                    grid_filas,
                    scrollable=True,
                    vertical_scroll_only=True,
                    size=(900, 520),
                    key="-GRID-",
                )
            ],
            [sg.HorizontalSeparator()],
            [
                sg.Text("Seleccionadas:", font=("Helvetica", 11)),
                sg.Text(
                    "Ninguna",
                    key="-RESUMEN-",
                    font=("Helvetica", 11, "bold"),
                    text_color="#dc3545",
                    size=(60, 1),
                ),
            ],
            [
                sg.Button(
                    "Seleccionar todas",
                    size=(16, 1),
                    font=("Helvetica", 10),
                    button_color=("white", "#6c757d"),
                ),
                sg.Button(
                    "Limpiar selección",
                    size=(16, 1),
                    font=("Helvetica", 10),
                    button_color=("white", "#6c757d"),
                ),
                sg.Push(),
                sg.Button(
                    "CANCELAR",
                    size=(12, 1),
                    font=("Helvetica", 11),
                    button_color=("white", "#dc3545"),
                ),
                sg.Button(
                    "CONTINUAR →",
                    size=(14, 1),
                    font=("Helvetica", 11, "bold"),
                    button_color=("white", "#28a745"),
                    key="-CONTINUAR-",
                    disabled=True,
                ),
            ],
        ]

        ventana = sg.Window(
            "Seleccionar Páginas para Firmar",
            layout,
            element_justification="c",
            finalize=True,
            resizable=True,
        )

        seleccionadas: set[int] = set()

        def _actualizar_resumen():
            if seleccionadas:
                nums = ", ".join(str(p + 1) for p in sorted(seleccionadas))
                ventana["-RESUMEN-"].update(
                    f"Páginas: {nums}  ({len(seleccionadas)} seleccionada(s))",
                    text_color="#28a745",
                )
                ventana["-CONTINUAR-"].update(disabled=False)
            else:
                ventana["-RESUMEN-"].update("Ninguna", text_color="#dc3545")
                ventana["-CONTINUAR-"].update(disabled=True)

        while True:
            ev, _ = ventana.read(timeout=200)

            if ev in (sg.WIN_CLOSED, "CANCELAR"):
                ventana.close()
                return None

            # Clic en miniatura: toggle selección
            if isinstance(ev, str) and ev.startswith("-PAG-"):
                idx = int(ev.split("-")[2])
                if idx in seleccionadas:
                    seleccionadas.remove(idx)
                    ventana[ev].update(button_color=("white", "#e9ecef"))
                    ventana[f"-LABEL-{idx}-"].update(text_color="black")
                else:
                    seleccionadas.add(idx)
                    ventana[ev].update(button_color=("white", "#ffc107"))
                    ventana[f"-LABEL-{idx}-"].update(text_color="#856404")
                _actualizar_resumen()

            if ev == "Seleccionar todas":
                for i in range(total):
                    seleccionadas.add(i)
                    ventana[f"-PAG-{i}-"].update(button_color=("white", "#ffc107"))
                    ventana[f"-LABEL-{i}-"].update(text_color="#856404")
                _actualizar_resumen()

            if ev == "Limpiar selección":
                for i in list(seleccionadas):
                    ventana[f"-PAG-{i}-"].update(button_color=("white", "#e9ecef"))
                    ventana[f"-LABEL-{i}-"].update(text_color="black")
                seleccionadas.clear()
                _actualizar_resumen()

            if ev == "-CONTINUAR-" and seleccionadas:
                ventana.close()
                return sorted(seleccionadas)

    except Exception as e:
        sg.popup_error(f"Error al procesar el PDF:\n{e}")
        print(f"[ERROR fase1] {e}")
        return None
