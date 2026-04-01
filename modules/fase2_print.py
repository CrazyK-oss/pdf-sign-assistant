# modules/fase2_print.py
# ROOT CAUSE DEFINITIVO (confirmado con test de bloques de color):
#
#   Resultado del test minimal:
#     Negro  (0,0,0)   -> negro    OK
#     Rojo   (255,0,0) -> rosa     ROTO
#     Verde  (0,255,0) -> blanco   ROTO
#     Azul   (0,0,255) -> morado   ROTO
#
#   Esto NO es un intercambio R<->B.
#   El canal R se filtra en todos los canales.
#   Patrón exacto de conversión RGB->CMYK mal aplicada:
#     el driver HP recibe los datos y los interpreta como CMYK
#     porque QPrinter.PrinterMode.HighResolution activa el pipeline
#     de alta calidad del driver, que en la HP Smart Tank 530
#     trabaja en espacio CMYK internamente.
#
# SOLUCIÓN:
#   QPrinter.PrinterMode.ScreenResolution mantiene el pipeline RGB
#   directo sin conversion CMYK. El driver recibe los datos tal cual.

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QPainter, QImage, QPixmap
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtWidgets import QMessageBox

try:
    import fitz
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

PRINT_DPI = 150


class ImpresionPagina:

    @staticmethod
    def imprimir(ruta_pdf: str, num_pagina: int, parent=None) -> bool:
        if not PYMUPDF_OK:
            QMessageBox.critical(
                parent,
                "Dependencia faltante",
                "PyMuPDF no está instalado.\n\n"
                "Instálalo con:\n    pip install pymupdf\n\n"
                "Luego reinicia la aplicación."
            )
            return False

        # ── 1. Configurar QPrinter ──────────────────────────────────────
        #
        # ScreenResolution = pipeline RGB directo al driver.
        # HighResolution   = pipeline CMYK de alta calidad (rompe colores
        #                    en la HP Smart Tank 530).
        printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
        printer.setResolution(PRINT_DPI)
        printer.setColorMode(QPrinter.ColorMode.Color)
        printer.setFullPage(True)

        try:
            with fitz.open(ruta_pdf) as doc_tmp:
                rect = doc_tmp[num_pagina].rect
                printer.setPageOrientation(
                    QPrinter.Orientation.Landscape if rect.width > rect.height
                    else QPrinter.Orientation.Portrait
                )
        except Exception:
            pass

        # ── 2. Diálogo nativo de Windows ───────────────────────────────
        dialog = QPrintDialog(printer, parent)
        dialog.setWindowTitle(f"Imprimir \u2014 P\u00e1gina {num_pagina + 1}")
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return False

        # ── 3. Renderizar con fitz ──────────────────────────────────────
        doc = None
        try:
            doc    = fitz.open(ruta_pdf)
            pagina = doc[num_pagina]
            zoom   = PRINT_DPI / 72.0
            pix    = pagina.get_pixmap(
                matrix=fitz.Matrix(zoom, zoom),
                colorspace=fitz.csRGB,
                alpha=False,
            )
        except Exception as e:
            QMessageBox.critical(
                parent,
                "Error al procesar el PDF",
                f"No se pudo renderizar la p\u00e1gina:\n\n{e}"
            )
            return False
        finally:
            if doc:
                doc.close()

        # ── 4. fitz -> QImage -> QPixmap ─────────────────────────────────
        img_rgb = QImage(
            bytes(pix.samples),
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        )
        pixmap = QPixmap.fromImage(img_rgb)

        # ── 5. Pintar ──────────────────────────────────────────────────
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(
                parent,
                "Error de impresión",
                "No se pudo iniciar el proceso de impresión.\n"
                "Verific\u00e1 que la impresora est\u00e9 disponible y sin errores."
            )
            return False

        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            viewport  = painter.viewport()
            pm_size   = pixmap.size().scaled(
                viewport.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            x_off = (viewport.width()  - pm_size.width())  // 2
            y_off = (viewport.height() - pm_size.height()) // 2
            painter.drawPixmap(
                QRect(x_off, y_off, pm_size.width(), pm_size.height()),
                pixmap,
            )
        finally:
            painter.end()

        return True
