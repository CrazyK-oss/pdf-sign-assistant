# modules/fase2_print.py
# Fase 2: Impresión de una página específica del PDF.
#
# Flujo:
#   1. Detecta automáticamente si la página tiene color real o es B/N.
#   2. Configura QPrinter (GrayScale / Color) según detección.
#   3. Abre el diálogo NATIVO de Windows (QPrintDialog) — que ya incluye
#      el thumbnail de vista previa integrado en el panel derecho.
#   4. Renderiza al DPI real de la impresora y pinta con QPainter.
#
# Fix color (café / morado):
#   El problema razíz es que QPainter sobre QPrinter necesita recibir
#   Format_ARGB32 (el formato interno nativo de Qt) para que no ocurra
#   ninguna re-interpretación de canales por parte del driver.
#   Usar Format_RGB888 o Format_Grayscale8 directamente hace que algunos
#   drivers (HP, Canon) reinterpreten los bytes como CMYK o BGR,
#   produciendo el tono café / morado.
#   Solución: renderizar con fitz.csRGB y convertir a Format_ARGB32
#   antes de pintar. Para documentos B/N le pedimos a Qt que convierta
#   al vuelo con convertToFormat — así el painter siempre ve ARGB32.

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QPainter, QImage
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtWidgets import QMessageBox

try:
    import fitz  # PyMuPDF
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False


# ─────────────────────────────────────────────────────────────────────────
#  Detección de color
# ─────────────────────────────────────────────────────────────────────────

def _pagina_tiene_color(pagina) -> bool:
    """
    Devuelve True si la página tiene algún píxel con saturación visible.
    Muestrea 2000 píxeles a 72 DPI (imagen mínima, muy rápido).
    Umbral de 20 para ignorar leves variaciones de perfil ICC.
    """
    try:
        pix = pagina.get_pixmap(
            matrix=fitz.Matrix(1, 1),
            colorspace=fitz.csRGB,
            alpha=False,
        )
        samples = pix.samples
        total   = pix.width * pix.height
        step    = max(1, total // 2000)
        for i in range(0, total, step):
            o = i * 3
            if max(samples[o], samples[o+1], samples[o+2]) \
             - min(samples[o], samples[o+1], samples[o+2]) > 20:
                return True
        return False
    except Exception:
        return True   # ante la duda: color


# ─────────────────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────────────────

class ImpresionPagina:
    """
    Clase utilitaria estática.

    Uso:
        from modules.fase2_print import ImpresionPagina
        if ImpresionPagina.imprimir(ruta_pdf, num_pagina, parent=self):
            self.pagina_seleccionada.emit(num_pagina)
    """

    @staticmethod
    def imprimir(ruta_pdf: str, num_pagina: int, parent=None) -> bool:
        """
        Abre el diálogo de impresión nativo de Windows con thumbnail
        integrado, y pinta la página del PDF con color correcto.

        Returns True si el usuario confirmó e imprimió.
        """
        if not PYMUPDF_OK:
            QMessageBox.critical(
                parent, "Dependencia faltante",
                "PyMuPDF no está instalado.\n\n"
                "Instálalo con:\n    pip install pymupdf\n\n"
                "Luego reinicia la aplicación."
            )
            return False

        # ── 1. Detectar color ─────────────────────────────────────────────
        tiene_color = True
        try:
            with fitz.open(ruta_pdf) as _doc:
                tiene_color = _pagina_tiene_color(_doc[num_pagina])
        except Exception:
            pass

        # ── 2. Configurar QPrinter ─────────────────────────────────────────
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setColorMode(
            QPrinter.ColorMode.Color if tiene_color
            else QPrinter.ColorMode.GrayScale
        )
        printer.setFullPage(True)

        try:
            with fitz.open(ruta_pdf) as _doc:
                rect = _doc[num_pagina].rect
                printer.setPageOrientation(
                    QPrinter.Orientation.Landscape if rect.width > rect.height
                    else QPrinter.Orientation.Portrait
                )
        except Exception:
            pass

        # ── 3. Diálogo nativo de Windows ─────────────────────────────────
        #
        # QPrintDialog es el diálogo nativo de Windows: incluye el panel
        # de configuración a la izquierda Y el thumbnail de vista previa
        # a la derecha de forma nativa (es el sistema el que lo genera,
        # no la aplicación). No necesitamos ningún diálogo extra.
        dialog = QPrintDialog(printer, parent)
        dialog.setWindowTitle(f"Imprimir — Página {num_pagina + 1}")
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return False

        # ── 4. Renderizar al DPI real de la impresora ─────────────────────
        dpi = printer.resolution()
        if dpi <= 0:
            dpi = 300
        dpi = min(dpi, 600)  # cap de seguridad RAM

        doc = None
        try:
            doc  = fitz.open(ruta_pdf)
            pag  = doc[num_pagina]
            zoom = dpi / 72.0
            mat  = fitz.Matrix(zoom, zoom)

            # Siempre renderizamos en RGB con fitz — es el único colorspace
            # que fitz garantiza 1:1 con el PDF. El manejo de grises lo
            # hacemos en el paso de conversión QImage (ver abajo).
            pix = pag.get_pixmap(
                matrix=mat,
                colorspace=fitz.csRGB,
                alpha=False,
            )
        except Exception as e:
            QMessageBox.critical(
                parent, "Error al procesar el PDF",
                f"No se pudo renderizar la página:\n\n{e}"
            )
            return False
        finally:
            if doc:
                doc.close()

        # ── 5. Convertir a QImage ARGB32 ──────────────────────────────────
        #
        # Por qué ARGB32 y no RGB888 / Grayscale8:
        #
        # QPainter sobre QPrinter en Windows delega en el driver de la
        # impresora a través de GDI / GDI+. GDI+ espera internamente que
        # los datos de imagen lleguen en formato BGRA (32 bpp). Qt mapea
        # Format_ARGB32 a BGRA32 en GDI+, por eso es el único formato
        # que se transfiere sin ningún canal de conversión adicional.
        #
        # Format_RGB888 hace que GDI+ reinterprete los 3 bytes como 4
        # (con padding incorrecto en algunos drivers HP/Canon), lo que
        # desplaza los canales R↔G↔B → aparece el tono morado o café.
        #
        # Pasos:
        #   a) Construir QImage en Format_RGB888 (los bytes de fitz son RGB).
        #   b) Convertir a Format_ARGB32 con convertToFormat — Qt hace
        #      la conversión internamente con alpha=255 (opaco).
        #      Si el documento es B/N, hacemos la conversión en dos pasos:
        #      RGB888 → Grayscale8 → ARGB32, así el driver recibe grises
        #      reales mapeados a ARGB, no los colores RGB originales.
        img_rgb = QImage(
            bytes(pix.samples),
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        )
        img_rgb.setDotsPerMeterX(int(dpi / 0.0254))
        img_rgb.setDotsPerMeterY(int(dpi / 0.0254))

        if not tiene_color:
            # B/N: colapsar a gris para que el driver use solo tinta K
            img_gray = img_rgb.convertToFormat(QImage.Format.Format_Grayscale8)
            img      = img_gray.convertToFormat(QImage.Format.Format_ARGB32)
        else:
            img = img_rgb.convertToFormat(QImage.Format.Format_ARGB32)

        # Propagar DPI a la imagen final (puede haberse perdido en la conversión)
        img.setDotsPerMeterX(int(dpi / 0.0254))
        img.setDotsPerMeterY(int(dpi / 0.0254))

        # ── 6. Pintar en la impresora ──────────────────────────────────────
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(
                parent, "Error de impresión",
                "No se pudo iniciar el proceso de impresión.\n"
                "Verificá que la impresora esté disponible y sin errores."
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
            dest  = QRect(x_off, y_off, img_size.width(), img_size.height())
            painter.drawImage(dest, img)
        finally:
            painter.end()

        return True
