# modules/fase2_print.py
# Fase 2: Impresión de una página específica del PDF.
# Abre directamente el diálogo nativo del sistema operativo,
# renderizando la página al DPI real de la impresora seleccionada.

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QPainter, QImage
from PyQt6.QtCore import Qt
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
            False → usuario canceló el diálogo, o hubo un error.
        """

        # ── Guardia de dependencia ──────────────────────────────────────
        if not PYMUPDF_OK:
            QMessageBox.critical(
                parent,
                "Dependencia faltante",
                "PyMuPDF no está instalado.\n\n"
                "Instálalo con:\n"
                "    pip install pymupdf\n\n"
                "Luego reinicia la aplicación."
            )
            return False

        # ── 1. Configurar QPrinter ──────────────────────────────────────
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setColorMode(QPrinter.ColorMode.Color)
        # fullPage=False: respeta los márgenes físicos de la impresora
        printer.setFullPage(False)

        # Detectar orientación real de la página en el PDF
        try:
            doc_tmp = fitz.open(ruta_pdf)
            rect = doc_tmp[num_pagina].rect   # unidades: puntos tipográficos (1pt = 1/72 in)
            doc_tmp.close()
            if rect.width > rect.height:
                printer.setPageOrientation(QPrinter.Orientation.Landscape)
            else:
                printer.setPageOrientation(QPrinter.Orientation.Portrait)
        except Exception:
            pass  # Si falla, dejamos la orientación por defecto del sistema

        # ── 2. Abrir el diálogo nativo ──────────────────────────────────
        dialog = QPrintDialog(printer, parent)
        dialog.setWindowTitle(f"Imprimir — Página {num_pagina + 1}")

        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return False   # Usuario canceló → no hacer nada, volver al grid

        # ── 3. Renderizar la página al DPI real de la impresora ─────────
        dpi = printer.resolution()
        if dpi <= 0:
            dpi = 300   # Fallback seguro si la impresora no reporta DPI

        try:
            doc = fitz.open(ruta_pdf)
            pagina = doc[num_pagina]

            # zoom = DPI_impresora / 72  →  resolución máxima garantizada
            # Ej: impresora 600 DPI → zoom = 8.33 → imagen ~4960×7016 px para A4
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = pagina.get_pixmap(matrix=mat, alpha=False)
            doc.close()

        except Exception as e:
            QMessageBox.critical(
                parent,
                "Error al procesar el PDF",
                f"No se pudo renderizar la página:\n\n{e}"
            )
            return False

        # ── 4. Convertir pixmap a QImage ────────────────────────────────
        img = QImage(
            pix.samples,       # buffer de bytes RGB
            pix.width,
            pix.height,
            pix.stride,        # bytes por fila
            QImage.Format.Format_RGB888
        )

        # ── 5. Pintar en la impresora ───────────────────────────────────
        painter = QPainter()

        if not painter.begin(printer):
            QMessageBox.critical(
                parent,
                "Error de impresión",
                "No se pudo iniciar el proceso de impresión.\n"
                "Verifica que la impresora esté disponible y sin errores."
            )
            return False

        try:
            # Escalar la imagen para ocupar toda la página, respetando proporción
            viewport = painter.viewport()
            img_size = img.size().scaled(
                viewport.size(),
                Qt.AspectRatioMode.KeepAspectRatio
            )

            # Centrar horizontalmente y verticalmente en la página
            x_off = (viewport.width()  - img_size.width())  // 2
            y_off = (viewport.height() - img_size.height()) // 2

            painter.setViewport(x_off, y_off, img_size.width(), img_size.height())
            painter.setWindow(img.rect())
            painter.drawImage(0, 0, img)

        finally:
            painter.end()   # Siempre liberar el painter, incluso si hay excepción

        return True