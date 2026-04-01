# modules/fase2_print.py
# ROOT CAUSE CONFIRMADO:
#   debug_fitz_output.png  -> normal  (fitz OK)
#   debug_qt_argb32.png    -> normal  (QImage OK)
#   impreso               -> morado  (QPainter->printer hace otra conversión interna)
#
# Qt en Windows, al llamar painter.drawImage() sobre un QPrinter,
# pasa la QImage por un QPixmap intermedio interno para el backend
# GDI, y esa conversión interna vuelve a intercambiar canales.
#
# SOLUCIÓN: convertir a QPixmap EXPLICITAMENTE nosotros antes de
# dibujar, y usar drawPixmap(). QPixmap es el formato nativo del
# display engine de Qt en Windows => cero conversiones intermedias.

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
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
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
        #
        # QPixmap es el formato nativo del display engine de Qt/Windows.
        # drawPixmap() sobre QPrinter no hace conversiones intermedias.
        # drawImage() sí las hace (pasa por un pixmap interno de GDI
        # que vuelve a intercambiar canales R<->B => morado).
        img_rgb = QImage(
            bytes(pix.samples),
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        )
        pixmap = QPixmap.fromImage(img_rgb)

        # ── 5. Pintar con drawPixmap ────────────────────────────────────
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
