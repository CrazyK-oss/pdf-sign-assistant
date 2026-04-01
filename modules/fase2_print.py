# modules/fase2_print.py
# Fase 2: Impresión de una página específica del PDF.
#
# Mejoras:
# - setFullPage(True): usa toda el área física de la hoja, sin márgenes
#   del controlador que recortarían el contenido.
# - Zoom calculado al DPI real de la impresora (sin cap) para máxima
#   resolución de trama. Impresoras de 600/1200 DPI se aprovechan al 100%.
# - drawImage con SmoothTransformation implícita (Qt escala la QImage
#   al destRect con bicúbico cuando la imagen es mayor que el destino).
# - Manejo explícito de memoria: doc.close() en bloque finally.

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QPainter, QImage
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtWidgets import QMessageBox

try:
    import fitz  # PyMuPDF
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False


class ImpresionPagina:
    """
    Clase utilitaria estática.
    Uso desde fase1_preview.py:

        from modules.fase2_print import ImpresionPagina
        imprimio = ImpresionPagina.imprimir(ruta_pdf, num_pagina, parent=self)
        if imprimio:
            self.pagina_seleccionada.emit(num_pagina)
    """

    @staticmethod
    def imprimir(ruta_pdf: str, num_pagina: int, parent=None) -> bool:
        """
        Abre el diálogo de impresión nativo del OS para la página indicada.

        Args:
            ruta_pdf:    Ruta absoluta al archivo PDF.
            num_pagina:  Índice 0-based de la página a imprimir.
            parent:      Widget padre para los diálogos (puede ser None).

        Returns:
            True  → usuario confirmó e imprimió.
            False → usuario canceló o hubo error.
        """
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

        # setFullPage(True): imprime en el área física total de la hoja.
        # Con False, el controlador aplica sus propios márgenes (~5-8 mm)
        # que recortan el contenido. True garantiza máximo aprovechamiento.
        printer.setFullPage(True)

        # Detectar orientación real de la página
        try:
            with fitz.open(ruta_pdf) as doc_tmp:
                rect = doc_tmp[num_pagina].rect
                if rect.width > rect.height:
                    printer.setPageOrientation(QPrinter.Orientation.Landscape)
                else:
                    printer.setPageOrientation(QPrinter.Orientation.Portrait)
        except Exception:
            pass

        # ── 2. Abrir el diálogo nativo ──────────────────────────────────
        dialog = QPrintDialog(printer, parent)
        dialog.setWindowTitle(f"Imprimir — Página {num_pagina + 1}")
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return False

        # ── 3. Renderizar al DPI real de la impresora ───────────────────
        dpi = printer.resolution()
        if dpi <= 0:
            dpi = 300

        doc = None
        try:
            doc = fitz.open(ruta_pdf)
            pagina = doc[num_pagina]

            # zoom = DPI_impresora / 72 pt  →  resolución 1:1 con la impresora
            # Ej: 600 DPI → zoom=8.33 → imagen ~4961×7016 px para A4 vertical
            # Ej: 1200 DPI → zoom=16.67 → imagen ~9922×14031 px
            zoom = dpi / 72.0
            mat  = fitz.Matrix(zoom, zoom)

            # colorspace=fitz.csRGB + alpha=False → RGB 24-bit sin canal alfa,
            # máxima compatibilidad con QPrinter y sin overhead de transparencia.
            pix = pagina.get_pixmap(
                matrix=mat,
                colorspace=fitz.csRGB,
                alpha=False,
            )
        except Exception as e:
            QMessageBox.critical(
                parent,
                "Error al procesar el PDF",
                f"No se pudo renderizar la página:\n\n{e}"
            )
            return False
        finally:
            if doc:
                doc.close()

        # ── 4. Convertir pixmap a QImage ────────────────────────────────
        img = QImage(
            bytes(pix.samples),  # buffer estable (memoryview → bytes)
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        )
        # Embeber DPI en la imagen para que QPrinter la posicione correctamente
        img.setDotsPerMeterX(int(dpi / 0.0254))
        img.setDotsPerMeterY(int(dpi / 0.0254))

        # ── 5. Pintar en la impresora ───────────────────────────────────
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(
                parent,
                "Error de impresión",
                "No se pudo iniciar el proceso de impresión.\n"
                "Verificá que la impresora esté disponible y sin errores."
            )
            return False

        try:
            # RenderHint SmoothPixmapTransform: activa interpolación bicúbica
            # al escalar la imagen al área del viewport → bordes nítidos.
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            viewport = painter.viewport()
            img_size = img.size().scaled(
                viewport.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            x_off = (viewport.width()  - img_size.width())  // 2
            y_off = (viewport.height() - img_size.height()) // 2
            dest_rect = QRect(x_off, y_off, img_size.width(), img_size.height())
            painter.drawImage(dest_rect, img)
        finally:
            painter.end()

        return True
