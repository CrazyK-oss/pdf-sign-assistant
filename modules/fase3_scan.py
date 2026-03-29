import platform
import subprocess
import time
from pathlib import Path
from PIL import Image
import PySimpleGUI as sg
from PyPDF2 import PdfReader, PdfWriter


TIMEOUT_SCAN_SEG = 120  # Tiempo máximo de espera por cada escaneo (segundos)
POLLING_INTERVAL = 1.0  # Frecuencia de revisión de carpeta de scans (segundos)


def _escanear_pagina(destino: Path) -> bool:
    """
    Activa el escáner y guarda el resultado como TIFF en 'destino'.
    Usa scanimage (Linux) o WIA/Windows Scan (Windows).
    """
    sistema = platform.system()
    try:
        if sistema == "Linux":
            subprocess.run(
                [
                    "scanimage",
                    "--format=tiff",
                    "--resolution=200",
                    f"--output-file={destino}",
                ],
                check=True,
                timeout=TIMEOUT_SCAN_SEG,
            )
        elif sistema == "Windows":
            # En Windows usamos WIA vía PowerShell (no requiere drivers extra para HP)
            script = (
                "$wia = New-Object -ComObject WIA.CommonDialog; "
                "$img = $wia.ShowAcquireImage(); "
                f'$img.SaveFile(\"{destino}\")'
            )
            subprocess.run(
                ["powershell", "-Command", script],
                check=True,
                timeout=TIMEOUT_SCAN_SEG,
            )
        else:
            sg.popup_error(f"Sistema no soportado para escaneo: {sistema}")
            return False
        print(f"[FASE 3] Página escaneada: {destino}")
        return True
    except subprocess.TimeoutExpired:
        sg.popup_error("El escáner tardó demasiado. Verifique que esté encendido y conectado.")
        return False
    except subprocess.CalledProcessError as e:
        sg.popup_error(f"Error al escanear:\n{e}")
        print(f"[ERROR fase3 scan] {e}")
        return False


def _tiff_a_pdf(tiff_path: Path, pdf_path: Path) -> bool:
    """Convierte un archivo TIFF escaneado a una página PDF."""
    try:
        img = Image.open(tiff_path)
        img_rgb = img.convert("RGB")  # TIFF puede ser modo L o RGBA; PDF necesita RGB
        img_rgb.save(str(pdf_path), "PDF", resolution=200)
        print(f"[FASE 3] TIFF convertido a PDF: {pdf_path}")
        return True
    except Exception as e:
        sg.popup_error(f"Error al convertir escaneo a PDF:\n{e}")
        print(f"[ERROR fase3 convert] {e}")
        return False


def _reemplazar_paginas(
    pdf_original: Path,
    paginas_originales: list[int],
    pdfs_escaneados: list[Path],
    destino: Path,
) -> bool:
    """
    Reemplaza las páginas 'paginas_originales' del PDF original con los PDFs escaneados
    y guarda el resultado en 'destino'.
    """
    try:
        reader_original = PdfReader(pdf_original)
        writer = PdfWriter()

        # Mapear índices originales → PDF escaneado correspondiente
        mapa_reemplazos = dict(zip(paginas_originales, pdfs_escaneados))

        for i in range(len(reader_original.pages)):
            if i in mapa_reemplazos:
                reader_scan = PdfReader(mapa_reemplazos[i])
                writer.add_page(reader_scan.pages[0])
                print(f"[FASE 3] Página {i + 1} reemplazada con escaneo.")
            else:
                writer.add_page(reader_original.pages[i])

        with open(destino, "wb") as f:
            writer.write(f)
        print(f"[FASE 3] PDF firmado generado: {destino}")
        return True
    except Exception as e:
        sg.popup_error(f"Error al reemplazar páginas en el PDF:\n{e}")
        print(f"[ERROR fase3 replace] {e}")
        return False


def escanear_y_reemplazar(
    pdf_original: Path,
    paginas: list[int],
    scans_dir: Path,
    pdf_firmado: Path,
) -> bool:
    """
    Gestiona el ciclo completo de escaneo para todas las páginas seleccionadas:
    escanea cada una, la convierte a PDF y reemplaza la página correspondiente
    en el documento original.

    Args:
        pdf_original: Path al PDF original sin firmar.
        paginas:      Lista de índices 0-based de páginas que se firmaron.
        scans_dir:    Carpeta donde guardar los TIFF/PDF de cada escaneo.
        pdf_firmado:  Path de salida para el PDF con páginas reemplazadas.

    Returns:
        True si todos los escaneos y el reemplazo fueron exitosos, False si se canceló.
    """
    total = len(paginas)
    pdfs_escaneados: list[Path] = []

    for num, idx_pagina in enumerate(paginas, start=1):
        # --- Pantalla de instrucción por cada página ---
        layout_scan = [
            [sg.Text("📠", font=("Helvetica", 48), justification="c")],
            [
                sg.Text(
                    f"Escaneo {num} de {total}",
                    font=("Helvetica", 16, "bold"),
                    justification="c",
                )
            ],
            [
                sg.Text(
                    f"Página {idx_pagina + 1} del documento",
                    font=("Helvetica", 13),
                    justification="c",
                    text_color="gray",
                )
            ],
            [sg.HorizontalSeparator(pad=(0, 15))],
            [
                sg.Text(
                    "Asegúrese de que la página firmada\n"
                    "está colocada correctamente en el escáner\ny presione ESCANEAR.",
                    font=("Helvetica", 13),
                    justification="c",
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
                    "ESCANEAR PÁGINA",
                    size=(20, 2),
                    button_color=("white", "#007BFF"),
                    font=("Helvetica", 12, "bold"),
                    key="-ESCANEAR-",
                ),
            ],
        ]

        ventana = sg.Window(
            f"Escanear página {idx_pagina + 1}",
            layout_scan,
            element_justification="c",
            size=(460, 360),
            finalize=True,
        )

        accion = None
        while True:
            ev, _ = ventana.read()
            if ev in (sg.WIN_CLOSED, "CANCELAR"):
                accion = "cancelar"
                break
            if ev == "-ESCANEAR-":
                accion = "escanear"
                break
        ventana.close()

        if accion == "cancelar":
            return False

        # --- Escanear y convertir ---
        tiff_path = scans_dir / f"scan_{num:03d}.tiff"
        pdf_scan_path = scans_dir / f"scan_{num:03d}.pdf"

        # Mostrar indicador de progreso mientras escanea
        sg.popup_animated(sg.DEFAULT_BASE64_LOADING_GIF, "Escaneando, por favor espere...", time_between_frames=100, no_titlebar=False)

        exito_scan = _escanear_pagina(tiff_path)
        sg.popup_animated(None)  # Cerrar animación

        if not exito_scan:
            return False

        if not _tiff_a_pdf(tiff_path, pdf_scan_path):
            return False

        pdfs_escaneados.append(pdf_scan_path)

        # Confirmación visual entre escaneos (si hay más páginas pendientes)
        if num < total:
            sg.popup_auto_close(
                f"✅ Página {idx_pagina + 1} escaneada correctamente.\n"
                f"Prepare la siguiente página ({paginas[num] + 1}) en el escáner.",
                title="Escaneo exitoso",
                auto_close_duration=3,
                no_titlebar=False,
            )

    # --- Reemplazar todas las páginas en el PDF original ---
    return _reemplazar_paginas(pdf_original, paginas, pdfs_escaneados, pdf_firmado)
