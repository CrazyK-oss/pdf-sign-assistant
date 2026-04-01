# modules/fase2_print.py
# Fase 2: Impresión de una página específica del PDF.
#
# DIAGNÓSTICO DEFINITIVO DEL MORADO
# ─────────────────────────────────────────────────────────────────────────────
# El código original (Format_RGB888 + drawImage) imprimía bien.
# El morado NO es un bug de Qt ni del código: es el ICM (Image Color
# Management) de Windows aplicando un perfil de color al bitmap RGB antes
# de mandárselo al driver HP Smart Tank.
#
# Windows GDI tiene ICM activado por defecto para impresoras. Cuando el
# driver HP recibe el bitmap, GDI aplica primero su perfil de color ICC
# (normalmente sRGB -> perfil del dispositivo). En la HP Smart Tank ese
# perfil tiene un error conocido: mapea el canal azul muy por encima del
# rojo -> los colores oscuros viajan hacia el morado.
#
# Solución: desactivar ICM en el contexto del dispositivo (HDC) de la
# impresora con SetICMMode(hdc, ICM_OFF) ANTES de que QPainter empiece
# a pintar. Así GDI pasa el bitmap RGB sin ninguna transformación y el
# driver recibe exactamente los bytes que generó fitz.
#
# Referencia: https://learn.microsoft.com/windows/win32/api/wingdi/nf-wingdi-seticmmode
# Referencia: Qt Forum -- "Printing a QImage has color distortion" (2016)
# ─────────────────────────────────────────────────────────────────────────────

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QPainter, QImage
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtWidgets import QMessageBox

try:
    import fitz
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

# ctypes para llamar a SetICMMode solo en Windows
try:
    import ctypes
    import ctypes.wintypes
    _gdi32 = ctypes.windll.gdi32
    ICM_OFF = 1
    _WIN32_OK = True
except Exception:
    _WIN32_OK = False


def _disable_icm(hdc_int: int) -> None:
    """Desactiva ICM (gestión de color de Windows) en el HDC dado."""
    if not _WIN32_OK or not hdc_int:
        return
    try:
        _gdi32.SetICMMode(ctypes.wintypes.HDC(hdc_int), ICM_OFF)
    except Exception:
        pass


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
                if rect.width > rect.height:
                    printer.setPageOrientation(QPrinter.Orientation.Landscape)
                else:
                    printer.setPageOrientation(QPrinter.Orientation.Portrait)
        except Exception:
            pass

        # ── 2. Diálogo nativo ───────────────────────────────────────────
        dialog = QPrintDialog(printer, parent)
        dialog.setWindowTitle(f"Imprimir \u2014 P\u00e1gina {num_pagina + 1}")
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return False

        # ── 3. Desactivar ICM en el HDC de Windows ──────────────────────
        # handle() solo es válido después de aceptar QPrintDialog.
        _disable_icm(printer.handle())

        # ── 4. Renderizar al DPI real ───────────────────────────────────
        dpi = printer.resolution()
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

        # ── 5. fitz pixmap → QImage RGB888 ─────────────────────────────
        img = QImage(
            bytes(pix.samples),
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        )
        img.setDotsPerMeterX(int(dpi / 0.0254))
        img.setDotsPerMeterY(int(dpi / 0.0254))

        # ── 6. Pintar ──────────────────────────────────────────────────
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
