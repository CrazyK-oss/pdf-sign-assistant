# modules/fase2_print.py
# Fase 2: Impresión de una página específica del PDF.
#
# Código original restaurado (QPrintDialog nativo + drawImage).
#
# POR QUÉ EL MORADO APARECIÓ:
#   El commit d9b35e8 quitó el cap de DPI para "máxima calidad".
#   A DPI >= 600 el driver HP Smart Tank activa su pipeline ICM
#   (Image Color Management) para modo foto, que aplica el perfil
#   ICC del dispositivo y desplaza los colores -> morado/café.
#   A DPI <= 300 el driver usa el pipeline de documentos simple,
#   sin gestión de color => colores exactos.
#
# SOLUCIÓN: cap de DPI en 300. La diferencia visual en documentos
# de texto y PDF firmados es imperceptible frente a 600 DPI, pero
# evita por completo el problema de color.

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QPainter, QImage
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
                parent,
                "Dependencia faltante",
                "PyMuPDF no está instalado.\n\n"
                "Instálalo con:\n    pip install pymupdf\n\n"
                "Luego reinicia la aplicación."
            )
            return False

        # ── 1. Configurar QPrinter ──────────────────────────────────────
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
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

        # ── 3. Renderizar ──────────────────────────────────────────────
        #
        # DPI CAP = 300.
        # Por encima de 300 DPI el driver HP activa ICM (modo foto)
        # y aplica su perfil de color ICC => resultado morado/café.
        # 300 DPI es más que suficiente para documentos y PDFs firmados.
        dpi = min(printer.resolution(), 300)
        if dpi <= 0:
            dpi = 300

        doc = None
        try:
            doc    = fitz.open(ruta_pdf)
            pagina = doc[num_pagina]
            zoom   = dpi / 72.0
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

        # ── 4. fitz pixmap → QImage ───────────────────────────────────
        img = QImage(
            bytes(pix.samples),
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        )
        img.setDotsPerMeterX(int(dpi / 0.0254))
        img.setDotsPerMeterY(int(dpi / 0.0254))

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
