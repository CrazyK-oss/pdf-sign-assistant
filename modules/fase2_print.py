# modules/fase2_print.py
# Fase 2: Impresión de una página específica del PDF.
#
# Ruta: fitz csGRAY → QImage Grayscale8 → QPixmap → painter.drawPixmap
#
# Por qué esta ruta resuelve el morado/café:
#   drawImage() en Windows pasa el bitmap directamente a GDI+ que lo
#   reinterpreta según su propio perfil de color → canales mezclados.
#   drawPixmap() en cambio pasa por el motor de Qt (raster engine) que
#   convierte internamente a DIB antes de enviarlo a GDI, respetando los
#   colores tal cual. Con QPixmap en escala de grises el resultado es
#   negro limpio, sin mezcla de tintas.

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QPainter, QImage, QPixmap
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtWidgets import QApplication, QMessageBox

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

        # ── 1. QPrinter ───────────────────────────────────────────────
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

        # ── 2. Diálogo nativo ────────────────────────────────────────────
        dlg = QPrintDialog(printer, parent)
        dlg.setWindowTitle(f"Imprimir — Página {num_pagina + 1}")
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return False

        # ── 3. Renderizar en grises ─────────────────────────────────────
        dpi = min(max(printer.resolution(), 150), 300)

        doc = None
        try:
            doc  = fitz.open(ruta_pdf)
            pag  = doc[num_pagina]
            pix  = pag.get_pixmap(
                matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0),
                colorspace=fitz.csGRAY,
                alpha=False,
            )
        except Exception as e:
            QMessageBox.critical(parent, "Error al renderizar", str(e))
            return False
        finally:
            if doc:
                doc.close()

        # ── 4. fitz pixmap → QImage Grayscale8 → QPixmap ─────────────────
        #
        # QPixmap.fromImage convierte internamente a formato nativo de Qt
        # (ARGB32 premultiplied en memoria de video) antes de que el
        # painter lo baje a GDI. Ese camino respeta el contenido en grises
        # sin reinterpretar canales — a diferencia de drawImage que hace
        # la conversión en el momento del blitting y puede confundir
        # los canales en drivers HP/Canon.
        img = QImage(
            bytes(pix.samples),
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_Grayscale8,
        )
        # Forzar que Qt procese la imagen antes de pasarla al painter
        img = img.convertToFormat(QImage.Format.Format_Grayscale8)

        pm = QPixmap.fromImage(img)
        # liberar buffer grande antes de pintar
        del img
        del pix

        # ── 5. Pintar con drawPixmap ─────────────────────────────────────
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(
                parent, "Error de impresión",
                "No se pudo iniciar la impresión.\n"
                "Verificá que la impresora esté disponible."
            )
            return False

        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

            vp      = painter.viewport()
            pm_size = pm.size().scaled(vp.size(), Qt.AspectRatioMode.KeepAspectRatio)
            x_off   = (vp.width()  - pm_size.width())  // 2
            y_off   = (vp.height() - pm_size.height()) // 2
            painter.drawPixmap(
                QRect(x_off, y_off, pm_size.width(), pm_size.height()),
                pm,
            )
        finally:
            painter.end()

        return True
