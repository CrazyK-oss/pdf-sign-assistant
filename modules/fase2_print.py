# modules/fase2_print.py
# Fase 2: Impresión de una página específica del PDF.
#
# ROOT CAUSE DEL MORADO (definitivo):
#   Format_RGB888 no es nativo en GDI (Windows).
#   Qt convierte internamente RGB888 -> BGRA para GDI, y en esa
#   conversión intercambia los canales R y B si el stride/alineación
#   no es múltiplo de 4 bytes => resultado morado/violeta en papel.
#   La solución es convertir la QImage a Format_ARGB32 (BGRA nativo
#   de GDI/Win32) ANTES de llamar a painter.drawImage().
#   Format_ARGB32 es el formato interno de GDI => cero conversión,
#   cero intercambio de canales, colores exactos.

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QPainter, QImage
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

        # ── 4. fitz pixmap → QImage RGB888 → convertir a ARGB32 ────────────
        #
        # GDI (Windows) usa BGRA (= ARGB32 en Qt) como formato nativo.
        # Si le pasamos Format_RGB888 directamente, Qt hace una
        # conversión interna con posible intercambio de canales R<->B
        # => morado en papel.
        # Convirtiendo a Format_ARGB32 ANTES de dibujar, Qt no necesita
        # hacer ninguna conversión adicional => colores exactos.
        img_rgb = QImage(
            bytes(pix.samples),
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        )
        # Conversión explícita: RGB888 -> ARGB32 (BGRA nativo de GDI)
        img = img_rgb.convertToFormat(QImage.Format.Format_ARGB32)
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

            viewport = painter.viewport()
            img_size = img.size().scaled(
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
