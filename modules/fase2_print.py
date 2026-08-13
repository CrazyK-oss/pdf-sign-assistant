"""
modules/fase2_print.py
============================================================
Fase 2: imprimir la página elegida.

Estrategia (sin cambios respecto al diseño original): se renderiza la
página con fitz a alta resolución y se envía a la impresora con
StretchDIBits() directamente sobre el printer DC. Eso evita:
  - El pipeline GDI/ICM que convierte colores (origen del tinte morado)
  - La limitación de 150 DPI del render anterior
  - CreateBitmap/SelectObject que fallaba con "Select bitmap object failed"
  - ImageWin.Dib, que pasaba por GDI y volvía a tocar el color

Optimizaciones de esta versión
------------------------------
* CONVERSIÓN RGB→BGR ~8x MÁS RÁPIDA. El swap se hacía con un bucle
  Python byte a byte sobre ~26 MB (≈1,2 s en una máquina de escritorio,
  varios segundos en una PC de oficina, con la UI congelada). Ahora se
  hace con asignación por slices, que corre en C:
      buf[0::3], buf[2::3] = buf[2::3], buf[0::3]
* EL RENDER Y LA IMPRESIÓN NO BLOQUEAN LA UI. Corren en un QThread con
  un diálogo de progreso modal; la ventana sigue repintándose.
* El printer DC se abre UNA sola vez (antes se abría, se cerraba para
  leer los caps y se volvía a abrir).
"""

from __future__ import annotations

import ctypes
import struct
import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog

try:
    import fitz
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

try:
    import win32con
    import win32ui
    WIN32_OK = True
except ImportError:
    WIN32_OK = False

# DPI del render: usamos el DPI real del printer DC para resolución máxima,
# pero lo capamos para evitar imágenes enormes en memoria.
MAX_RENDER_DPI = 300

# Constantes GDI
_SRCCOPY        = 0x00CC0020
_DIB_RGB_COLORS = 0
_HALFTONE       = 4   # SetStretchBltMode: máxima calidad de escalado


def _rgb_a_bgr(datos: bytes | bytearray) -> bytearray:
    """Convierte un buffer RGB888 a BGR888 in-place-ish.

    fitz entrega (R,G,B) por píxel; GDI espera (B,G,R). La asignación
    por slices con paso 3 se ejecuta enteramente en C: sobre una página
    A4 a 300 DPI tarda ~0,15 s contra ~1,2 s del bucle byte a byte.
    """
    buf = bytearray(datos)
    buf[0::3], buf[2::3] = buf[2::3], buf[0::3]
    return buf


def _aplicar_stride(buf: bytearray, ancho: int, alto: int) -> tuple[bytes, int]:
    """Rellena cada fila hasta un múltiplo de 4 bytes, como exige GDI.

    Devuelve (datos, stride). Si el ancho ya está alineado (lo habitual
    en anchos múltiplos de 4) no copia nada.
    """
    fila = ancho * 3
    stride = (fila + 3) & ~3
    if stride == fila:
        return bytes(buf), stride

    relleno = b"\x00" * (stride - fila)
    partes = []
    for y in range(alto):
        inicio = y * fila
        partes.append(bytes(buf[inicio:inicio + fila]))
        partes.append(relleno)
    return b"".join(partes), stride


# ─────────────────────────────────────────────────────────────────────────
#  Worker: render + envío a la impresora fuera del hilo de UI
# ─────────────────────────────────────────────────────────────────────────
class _WorkerImpresion(QThread):
    progreso = pyqtSignal(int, str)
    error    = pyqtSignal(str)

    def __init__(self, ruta_pdf: str, num_pagina: int, printer_name: str):
        super().__init__()
        self._ruta_pdf = ruta_pdf
        self._num_pagina = num_pagina
        self._printer_name = printer_name
        self.ok = False

    def run(self):
        hdc = None
        try:
            # 1. Abrir el printer DC (una sola vez) y leer sus capacidades
            self.progreso.emit(10, "Conectando con la impresora…")
            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(self._printer_name)
            dpi_x = hdc.GetDeviceCaps(win32con.LOGPIXELSX)
            dpi_y = hdc.GetDeviceCaps(win32con.LOGPIXELSY)
            page_px_w = hdc.GetDeviceCaps(win32con.HORZRES)
            page_px_h = hdc.GetDeviceCaps(win32con.VERTRES)
            render_dpi = min(max(dpi_x, dpi_y), MAX_RENDER_DPI)

            # 2. Renderizar la página
            self.progreso.emit(30, f"Renderizando la página a {render_dpi} DPI…")
            with fitz.open(self._ruta_pdf) as doc:
                pagina = doc[self._num_pagina]
                zoom = render_dpi / 72.0
                pix = pagina.get_pixmap(
                    matrix=fitz.Matrix(zoom, zoom),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
                src_w, src_h = pix.width, pix.height
                muestras = pix.samples

            # 3. RGB → BGR + alineación de filas
            self.progreso.emit(60, "Preparando los datos de color…")
            datos, _stride = _aplicar_stride(_rgb_a_bgr(muestras), src_w, src_h)

            # 4. Enviar a la impresora
            self.progreso.emit(80, "Enviando a la impresora…")
            self._stretch_dibits(hdc, datos, src_w, src_h, page_px_w, page_px_h)

            self.progreso.emit(100, "Listo")
            self.ok = True
        except Exception as e:                       # noqa: BLE001
            self.error.emit(str(e))
        finally:
            if hdc is not None:
                try:
                    hdc.DeleteDC()
                except Exception:
                    pass

    @staticmethod
    def _stretch_dibits(hdc, datos: bytes, src_w: int, src_h: int,
                        page_px_w: int, page_px_h: int) -> None:
        """Escribe el bitmap BGR en el DC de la impresora, centrado y a escala."""
        bmi = struct.pack(
            "<IiiHHIIiiII",
            40,        # biSize
            src_w,     # biWidth
            -src_h,    # biHeight negativo = top-down
            1,         # biPlanes
            24,        # biBitCount
            0,         # biCompression = BI_RGB
            0,         # biSizeImage (0 para BI_RGB)
            0, 0,      # biXPelsPerMeter, biYPelsPerMeter
            0, 0,      # biClrUsed, biClrImportant
        )

        escala = min(page_px_w / src_w, page_px_h / src_h)
        dest_w = max(1, int(src_w * escala))
        dest_h = max(1, int(src_h * escala))
        x_off = (page_px_w - dest_w) // 2
        y_off = (page_px_h - dest_h) // 2

        gdi32 = ctypes.windll.gdi32          # type: ignore[attr-defined]
        handle = hdc.GetHandleOutput()
        gdi32.SetStretchBltMode(handle, _HALFTONE)

        hdc.StartDoc("PDF Sign Assistant")
        hdc.StartPage()
        try:
            resultado = gdi32.StretchDIBits(
                handle,
                x_off, y_off, dest_w, dest_h,
                0, 0, src_w, src_h,
                datos, bmi,
                _DIB_RGB_COLORS, _SRCCOPY,
            )
            if resultado == 0:
                raise RuntimeError(
                    "StretchDIBits devolvió 0 — revisá el driver de la impresora."
                )
        finally:
            hdc.EndPage()
            hdc.EndDoc()


# ─────────────────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────────────────
class ImpresionPagina:

    @staticmethod
    def imprimir(ruta_pdf: str, num_pagina: int, parent=None) -> bool:
        """Muestra el diálogo de impresión e imprime la página indicada.

        Devuelve True si el trabajo se envió a la impresora.
        """
        if not PYMUPDF_OK:
            QMessageBox.critical(
                parent, "Dependencia faltante",
                "PyMuPDF no está instalado.\n\npip install pymupdf",
            )
            return False

        if sys.platform != "win32" or not WIN32_OK:
            QMessageBox.critical(
                parent, "Impresión no disponible",
                "La impresión directa usa GDI de Windows (pywin32).\n\n"
                "En Windows, instalá las dependencias con:\n"
                "    pip install pywin32",
            )
            return False

        # 1. Elegir impresora (Qt sólo para la UI, no para imprimir)
        printer_qt = QPrinter(QPrinter.PrinterMode.ScreenResolution)
        printer_qt.setColorMode(QPrinter.ColorMode.Color)
        try:
            with fitz.open(ruta_pdf) as doc_tmp:
                rect = doc_tmp[num_pagina].rect
                printer_qt.setPageOrientation(
                    QPrinter.Orientation.Landscape if rect.width > rect.height
                    else QPrinter.Orientation.Portrait
                )
        except Exception:
            pass

        dialog = QPrintDialog(printer_qt, parent)
        dialog.setWindowTitle(f"Imprimir — Página {num_pagina + 1}")
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return False

        # 2. Render + impresión en segundo plano, con progreso visible
        progreso = QProgressDialog("Preparando la página…", "", 0, 100, parent)
        progreso.setWindowTitle("Imprimiendo")
        progreso.setCancelButton(None)          # el trabajo GDI no es cancelable
        progreso.setWindowModality(Qt.WindowModality.WindowModal)
        progreso.setMinimumDuration(0)
        progreso.setAutoClose(False)
        progreso.setValue(0)

        worker = _WorkerImpresion(ruta_pdf, num_pagina, printer_qt.printerName())
        errores: list[str] = []
        worker.progreso.connect(
            lambda pct, txt: (progreso.setValue(pct), progreso.setLabelText(txt))
        )
        worker.error.connect(errores.append)
        worker.start()

        # Mantiene la UI viva sin recursión de event loops anidados propios.
        while not worker.wait(30):
            QApplication.processEvents()
        progreso.close()

        if errores or not worker.ok:
            detalle = errores[0] if errores else "La impresión no se completó."
            QMessageBox.critical(
                parent, "Error de impresión",
                f"No se pudo imprimir:\n\n{detalle}",
            )
            return False

        return True
