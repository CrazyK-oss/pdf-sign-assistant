# modules/fase2_print.py
# Fase 2: Impresión de una página específica del PDF.
#
# DIAGNÓSTICO FINAL CONFIRMADO:
#   - El PDF tiene R=0 G=0 B=0 para el texto negro. fitz lo renderiza
#     perfecto. El morado lo genera el driver HP Smart Tank al procesar
#     el bitmap por GDI con ICM activado.
#
#   - min(printer.resolution(), 300) NO funciona porque resolution()
#     es solo lectura después del diálogo; Qt usa el valor del driver
#     (600 DPI) para el viewport interno aunque nosotros rend. a 300.
#     Resultado: GDI escala la imagen de 300 a 600 DPI internamente
#     y el pipeline ICM se sigue activando.
#
# SOLUCIÓN DEFINITIVA:
#   printer.setResolution(150) ANTES de QPrintDialog.
#   Esto le dice a Qt que negocie 150 DPI con el driver, de forma que
#   el viewport interno de QPainter queda a 150 DPI y GDI no activa
#   su pipeline de alta resolución / ICM.
#   150 DPI es más que suficiente para documentos de texto/firmas.

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QPainter, QImage
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtWidgets import QMessageBox

try:
    import fitz
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

# DPI fijo para impresión. 150 evita el pipeline ICM del driver HP.
# Calidad: A4 a 150 DPI = 1240x1754 px, perfecta para texto y firmas.
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

        # ── 1. Configurar QPrinter con DPI fijo ANTES del diálogo ──────────
        #
        # setResolution() debe llamarse ANTES de QPrintDialog para que
        # Qt negocie ese DPI con el driver desde el inicio.
        # Si se llama después, el driver ya fijó su DPI interno (600)
        # y el setResolution queda ignorado.
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

        # ── 3. Renderizar al DPI fijo ───────────────────────────────────
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

        # ── 4. fitz pixmap → QImage RGB888 ─────────────────────────────
        img = QImage(
            bytes(pix.samples),
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        )
        img.setDotsPerMeterX(int(PRINT_DPI / 0.0254))
        img.setDotsPerMeterY(int(PRINT_DPI / 0.0254))

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
            img_size  = img.size().scaled(
                viewport.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            x_off = (viewport.width()  - img_size.width())  // 2
            y_off = (viewport.height() - img_size.height()) // 2
            painter.drawImage(
                QRect(x_off, y_off, img_size.width(), img_size.height()),
                img,
            )
        finally:
            painter.end()

        return True
