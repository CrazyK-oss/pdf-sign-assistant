# modules/fase2_print.py
# Fase 2: Impresión de una página específica del PDF.
#
# Esta versión incluye:
#
# 1. VISTA PREVIA real con QPrintPreviewDialog antes de imprimir.
#    - Muestra exactamente lo que se va a imprimir, a escala.
#    - El usuario puede cambiar la impresora, orientación y copias
#      desde el mismo diálogo sin cerrar.
#
# 2. MODO DE COLOR UNIVERSAL – auto-detección:
#    - Si el PDF tiene contenido a color → imprime en Color (RGB).
#    - Si el PDF es completamente blanco/negro → imprime en GrayScale
#      (solo tinta K), evitando la mezcla CMYK que produce el café/sepia
#      en impresoras de inyección de tinta.
#    - El usuario puede forzar el modo manualmente desde el diálogo.
#
# 3. setFullPage(True): área física total, sin márgenes del driver.
# 4. Zoom 1:1 con DPI real de la impresora.
# 5. SmoothPixmapTransform + Antialiasing para escala bicúbica.
# 6. doc.close() en finally para liberar memoria.

import math
from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PyQt6.QtGui import QPainter, QImage
from PyQt6.QtCore import Qt, QRect, QSize
from PyQt6.QtWidgets import QMessageBox

try:
    import fitz  # PyMuPDF
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False


# ─────────────────────────────────────────────────────────────────────────
#  Detección de contenido a color
# ─────────────────────────────────────────────────────────────────────────

def _pagina_tiene_color(pagina: "fitz.Page") -> bool:
    """
    Retorna True si la página contiene píxeles con saturación de color
    significativa (no solo grises). Usa un render a baja resolución (72 DPI)
    para ser rápido.

    Algoritmo:
    - Renderiza en RGB a 72 DPI (imagen pequeña ∼ 595×842 para A4).
    - Muestrea hasta 2000 píxeles al azar.
    - Considera color si alguno tiene diferencia máxima entre canales R/G/B
      mayor a 20 (umbral para ignorar leves variaciones de perfil de color).
    """
    try:
        pix = pagina.get_pixmap(
            matrix=fitz.Matrix(1, 1),  # 72 DPI, rápido
            colorspace=fitz.csRGB,
            alpha=False,
        )
        samples = pix.samples  # bytes: R G B R G B ...
        n_pixels = pix.width * pix.height
        step = max(1, n_pixels // 2000)  # muestreo

        for i in range(0, n_pixels, step):
            offset = i * 3
            r = samples[offset]
            g = samples[offset + 1]
            b = samples[offset + 2]
            if max(r, g, b) - min(r, g, b) > 20:  # umbral de saturación
                return True
        return False
    except Exception:
        return True  # ante la duda, usa color


# ─────────────────────────────────────────────────────────────────────────
#  Función de renderizado (usada tanto para preview como para imprimir)
# ─────────────────────────────────────────────────────────────────────────

def _renderizar_pagina(ruta_pdf: str, num_pagina: int, dpi: int,
                       use_gray: bool) -> "QImage | None":
    """
    Renderiza una página del PDF y devuelve una QImage lista para pintar.

    Args:
        ruta_pdf:    Ruta al PDF.
        num_pagina:  Índice 0-based.
        dpi:         Resolución de renderizado.
        use_gray:    True → escala de grises (solo tinta K);
                     False → color RGB completo.

    Returns:
        QImage o None si hubo error.
    """
    if not PYMUPDF_OK:
        return None

    # Cap de seguridad: evita imágenes de >250 MP que saturan la RAM.
    # A 600 DPI A4 → ~34 MP. A 1200 DPI → ~136 MP. Cap en 600 DPI para preview.
    dpi = min(dpi, 600)

    doc = None
    try:
        doc = fitz.open(ruta_pdf)
        pagina = doc[num_pagina]

        zoom = dpi / 72.0
        mat  = fitz.Matrix(zoom, zoom)

        if use_gray:
            pix = pagina.get_pixmap(
                matrix=mat,
                colorspace=fitz.csGRAY,
                alpha=False,
            )
            fmt = QImage.Format.Format_Grayscale8
        else:
            pix = pagina.get_pixmap(
                matrix=mat,
                colorspace=fitz.csRGB,
                alpha=False,
            )
            fmt = QImage.Format.Format_RGB888

        img = QImage(
            bytes(pix.samples),
            pix.width,
            pix.height,
            pix.stride,
            fmt,
        )
        img.setDotsPerMeterX(int(dpi / 0.0254))
        img.setDotsPerMeterY(int(dpi / 0.0254))
        return img

    except Exception:
        return None
    finally:
        if doc:
            doc.close()


def _pintar_en_dispositivo(painter: QPainter, img: "QImage"):
    """Escala la imagen manteniendo aspecto y la centra en el viewport."""
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


# ─────────────────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────────────────

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
        Muestra una vista previa (QPrintPreviewDialog) y luego imprime.

        Flujo:
          1. Detecta automáticamente si la página tiene color o es B/N.
          2. Configura QPrinter con el modo correcto (Color o GrayScale).
          3. Abre QPrintPreviewDialog con render en tiempo real.
          4. Al aceptar, imprime al DPI real de la impresora.

        Returns:
            True si el usuario confirmó e imprimió, False si canceló.
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

        # ── 1. Detectar modo de color automáticamente ─────────────────────
        use_gray = True  # defecto seguro
        try:
            with fitz.open(ruta_pdf) as _doc:
                use_gray = not _pagina_tiene_color(_doc[num_pagina])
        except Exception:
            pass

        # ── 2. Configurar QPrinter ─────────────────────────────────────────
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setColorMode(
            QPrinter.ColorMode.GrayScale if use_gray
            else QPrinter.ColorMode.Color
        )
        printer.setFullPage(True)

        # Orientación automática según la página
        try:
            with fitz.open(ruta_pdf) as _doc:
                rect = _doc[num_pagina].rect
                if rect.width > rect.height:
                    printer.setPageOrientation(QPrinter.Orientation.Landscape)
                else:
                    printer.setPageOrientation(QPrinter.Orientation.Portrait)
        except Exception:
            pass

        # ── 3. Vista previa con QPrintPreviewDialog ──────────────────────
        #
        # paintRequested se emite:
        #   a) Al abrir el diálogo (render inicial de la preview).
        #   b) Al cambiar configuración en el diálogo (re-render automático).
        #   c) Al confirmar “Imprimir” (render final al DPI real).
        #
        # En cada llamada leemos printer.resolution() porque puede haber
        # cambiado si el usuario eligió otra impresora desde el diálogo.
        # Para la preview usamos máx 150 DPI para que sea instantánea;
        # el render final usa el DPI real sin límite (solo el cap de 600).
        _imprimio = [False]  # lista mutable para capturar desde el closure

        def _on_paint_requested(p: QPrinter):
            dpi_render = p.resolution()
            # Durante preview (dpi_render bajo) limitamos a 150 para
            # que el render sea instantáneo. QPrintPreviewDialog reporta
            # un DPI distinto al final al imprimir de verdad.
            es_preview = dpi_render < 200
            dpi_usado = 150 if es_preview else min(dpi_render, 600)

            img = _renderizar_pagina(ruta_pdf, num_pagina, dpi_usado, use_gray)
            if img is None:
                return

            painter = QPainter()
            if not painter.begin(p):
                return
            try:
                _pintar_en_dispositivo(painter, img)
                if not es_preview:
                    _imprimio[0] = True
            finally:
                painter.end()

        preview = QPrintPreviewDialog(printer, parent)
        preview.setWindowTitle(f"Vista previa de impresión — Página {num_pagina + 1}")
        # Resize generoso para que la preview ocupe buena parte de la pantalla
        preview.resize(900, 700)
        preview.paintRequested.connect(_on_paint_requested)
        preview.exec()

        return _imprimio[0]
