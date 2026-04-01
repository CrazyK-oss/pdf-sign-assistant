# modules/fase2_print.py
# Fase 2: Impresión de una página específica del PDF.
#
# Modo: blanco y negro estricto.
# - fitz renderiza en escala de grises pura (csGRAY).
# - QPainter dibuja rect blanco de fondo y luego pinta cada píxel
#   oscuro como rect negro sólido — sin involucrar QImage ni el
#   pipeline de color del driver (GDI+).
# - Esto elimina cualquier problema de interpretación de canales
#   (morado/café) porque nunca se envían datos de imagen: solo
#   comandos vectoriales de relleno negro sobre blanco.
# - setColorMode(GrayScale): instrucción adicional al driver.
# - setFullPage(True): sin márgenes del driver.

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QPainter, QColor, QImage
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtWidgets import QMessageBox

try:
    import fitz
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False


class ImpresionPagina:

    @staticmethod
    def imprimir(ruta_pdf: str, num_pagina: int, parent=None) -> bool:
        if not PYMUPDF_OK:
            QMessageBox.critical(
                parent, "Dependencia faltante",
                "PyMuPDF no está instalado.\n\npip install pymupdf"
            )
            return False

        # ── 1. Configurar QPrinter ────────────────────────────────────────
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setColorMode(QPrinter.ColorMode.GrayScale)
        printer.setFullPage(True)

        try:
            with fitz.open(ruta_pdf) as _d:
                r = _d[num_pagina].rect
                printer.setPageOrientation(
                    QPrinter.Orientation.Landscape if r.width > r.height
                    else QPrinter.Orientation.Portrait
                )
        except Exception:
            pass

        # ── 2. Diálogo nativo ──────────────────────────────────────────
        dlg = QPrintDialog(printer, parent)
        dlg.setWindowTitle(f"Imprimir — Página {num_pagina + 1}")
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return False

        # ── 3. Renderizar en grises a DPI real ───────────────────────────
        dpi  = max(printer.resolution(), 300)
        dpi  = min(dpi, 600)
        doc  = None
        try:
            doc  = fitz.open(ruta_pdf)
            pag  = doc[num_pagina]
            zoom = dpi / 72.0
            # csGRAY: 1 byte por píxel, valores 0 (negro) a 255 (blanco)
            pix  = pag.get_pixmap(
                matrix=fitz.Matrix(zoom, zoom),
                colorspace=fitz.csGRAY,
                alpha=False,
            )
        except Exception as e:
            QMessageBox.critical(parent, "Error al renderizar", str(e))
            return False
        finally:
            if doc:
                doc.close()

        # ── 4. Pintar con QPainter usando solo fillRect negro/blanco ────────
        #
        # En lugar de drawImage (que pasa datos crudos al driver y puede
        # provocar interpretación incorrecta de canales), usamos el API
        # vectorial de QPainter: fillRect con QColor negro u blanco.
        # El driver recibe comandos de relleno sólido, no bitmaps —
        # imposible que confunda canales.
        #
        # Estrategia: escalar el pixmap al viewport manteniendo aspecto,
        # calcular el tamaño de cada "celda" (1 píxel del render = 1 rect
        # de impresión), pintar blanco de fondo y rellenar en negro cada
        # píxel con luminosidad < umbral.
        #
        # UMBRAL DE BINARIZACIÓN: 180
        # Píxeles con valor < 180 (gris oscuro a negro) → negro
        # Píxeles con valor >= 180 (gris claro a blanco) → blanco
        # Esto asegura que el texto y sellos queden sólidos, y el fondo
        # de la hoja quede limpio sin manchas grises.
        UMBRAL = 180

        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(
                parent, "Error de impresión",
                "No se pudo iniciar la impresión.\n"
                "Verificá que la impresora esté disponible."
            )
            return False

        try:
            vp = painter.viewport()
            vw, vh = vp.width(), vp.height()
            pw, ph = pix.width, pix.height

            # Escala manteniendo aspecto, centrado
            scale   = min(vw / pw, vh / ph)
            out_w   = int(pw * scale)
            out_h   = int(ph * scale)
            off_x   = (vw - out_w) // 2
            off_y   = (vh - out_h) // 2

            # Tamaño de cada "celda" de píxel en coordenadas de impresora
            # Usamos flotantes para acumular error y evitar gaps
            cx = out_w / pw
            cy = out_h / ph

            # Fondo blanco
            painter.fillRect(QRect(off_x, off_y, out_w, out_h),
                             QColor(255, 255, 255))

            samples = pix.samples  # bytes 0-255, un byte por píxel
            negro   = QColor(0, 0, 0)

            # Recorrer solo píxeles oscuros (la mayoría del documento es
            # blanco, así que esto es eficiente para páginas de texto)
            for y in range(ph):
                row_offset = y * pw
                y0 = off_y + int(y * cy)
                y1 = off_y + int((y + 1) * cy)
                rh = max(1, y1 - y0)
                for x in range(pw):
                    if samples[row_offset + x] < UMBRAL:
                        x0 = off_x + int(x * cx)
                        x1 = off_x + int((x + 1) * cx)
                        rw = max(1, x1 - x0)
                        painter.fillRect(QRect(x0, y0, rw, rh), negro)
        finally:
            painter.end()

        return True
