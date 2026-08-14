"""
modules/fase2_print.py
============================================================
Fase 2: imprimir las páginas elegidas.

Estrategia (sin cambios respecto al diseño original): se renderiza cada
página con fitz a alta resolución y se envía a la impresora con
StretchDIBits() directamente sobre el printer DC. Eso evita:
  - El pipeline GDI/ICM que convierte colores (origen del tinte morado)
  - La limitación de 150 DPI del render anterior
  - CreateBitmap/SelectObject que fallaba con "Select bitmap object failed"
  - ImageWin.Dib, que pasaba por GDI y volvía a tocar el color

Multipágina
-----------
Todas las páginas seleccionadas viajan en UN SOLO trabajo de impresión
(un StartDoc con varios StartPage/EndPage). Así la impresora no intercala
otros trabajos en el medio y la cola muestra un único ítem, que es lo que
espera quien está parado al lado de la impresora esperando sus hojas.
Se renderiza de a una página por vez: un documento de 20 páginas no
levanta 500 MB de bitmaps en memoria.

Optimizaciones
--------------
* CONVERSIÓN RGB→BGR ~8x MÁS RÁPIDA. El swap se hacía con un bucle
  Python byte a byte sobre ~26 MB (≈1,2 s por página, con la UI
  congelada). Ahora usa asignación por slices, que corre en C:
      buf[0::3], buf[2::3] = buf[2::3], buf[0::3]
* EL RENDER Y LA IMPRESIÓN NO BLOQUEAN LA UI: corren en un QThread con
  diálogo de progreso, que además informa página por página.
* El printer DC se abre UNA sola vez.
"""

from __future__ import annotations

import ctypes
import logging
import struct

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from modules.dispositivos import (
    DPI_REINTENTOS,
    ErrorDispositivo,
    contexto_impresora,
    leer_capacidades,
    verificar_impresion_disponible,
)
from modules.trabajo import formatear_paginas

log = logging.getLogger(__name__)

try:
    import fitz
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

# Constantes GDI
_SRCCOPY        = 0x00CC0020
_DIB_RGB_COLORS = 0
_HALFTONE       = 4   # SetStretchBltMode: máxima calidad de escalado


def _rgb_a_bgr(datos: bytes | bytearray) -> bytearray:
    """Convierte un buffer RGB888 a BGR888.

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
    aviso    = pyqtSignal(str)      # problemas no fatales, para el log/estado

    def __init__(self, ruta_pdf: str, paginas: list[int], printer_name: str):
        super().__init__()
        self._ruta_pdf = ruta_pdf
        self._paginas = list(paginas)
        self._printer_name = printer_name
        self.ok = False
        self.impresas = 0

    def run(self):
        total = len(self._paginas)
        if not total:
            self.error.emit("No hay páginas para imprimir.")
            return

        try:
            self.progreso.emit(2, "Conectando con la impresora…")
            with contexto_impresora(self._printer_name) as hdc:
                # Las capacidades pasan por el saneador: un driver que
                # informa 0 DPI o 0 de área ya no rompe ni imprime en blanco.
                caps = leer_capacidades(hdc)
                if caps.fue_corregida:
                    self.aviso.emit(" ".join(caps.correcciones))

                gdi32 = ctypes.windll.gdi32      # type: ignore[attr-defined]
                handle = hdc.GetHandleOutput()
                gdi32.SetStretchBltMode(handle, _HALFTONE)

                # Un único trabajo de impresión para todas las páginas.
                # El try/finally interno garantiza que un trabajo abierto
                # se aborte: si queda a medias, traba la cola de impresión.
                hdc.StartDoc("PDF Sign Assistant")
                terminado = False
                try:
                    with fitz.open(self._ruta_pdf) as doc:
                        for i, num_pagina in enumerate(self._paginas):
                            self._imprimir_una(doc, hdc, gdi32, handle, caps,
                                               num_pagina, i, total)
                            self.impresas += 1
                    hdc.EndDoc()
                    terminado = True
                finally:
                    if not terminado:
                        try:
                            hdc.AbortDoc()
                        except Exception:            # noqa: BLE001
                            pass

            self.progreso.emit(100, "Listo")
            self.ok = True

        except ErrorDispositivo as e:
            self.error.emit(e.texto_completo())
        except Exception as e:                       # noqa: BLE001
            self.error.emit(str(e))

    def _imprimir_una(self, doc, hdc, gdi32, handle, caps,
                      num_pagina: int, indice: int, total: int) -> None:
        """Renderiza y envía una página, bajando el DPI si hace falta.

        Algunas impresoras (sobre todo las de red y las económicas)
        rechazan bitmaps grandes con un error genérico o se quedan sin
        memoria. En vez de abortar el trabajo entero, se reintenta a
        menor resolución: una hoja a 150 DPI es infinitamente mejor que
        ninguna hoja.
        """
        base = int(indice / total * 96)
        dpis = [caps.dpi] + [d for d in DPI_REINTENTOS if d < caps.dpi]
        ultimo_error: Exception | None = None

        for intento, dpi in enumerate(dpis):
            try:
                sufijo = "" if intento == 0 else f" (reintento a {dpi} DPI)"
                self.progreso.emit(
                    base + 2,
                    f"Renderizando página {num_pagina + 1} "
                    f"({indice + 1} de {total}) a {dpi} DPI{sufijo}…")

                zoom = dpi / 72.0
                pix = doc[num_pagina].get_pixmap(
                    matrix=fitz.Matrix(zoom, zoom),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
                src_w, src_h = pix.width, pix.height
                muestras = pix.samples
                del pix              # libera el bitmap de fitz cuanto antes

                if src_w <= 0 or src_h <= 0:
                    raise ValueError(
                        f"El render de la página {num_pagina + 1} salió vacío.")

                self.progreso.emit(
                    base + 5, f"Preparando página {num_pagina + 1}…")
                datos, _stride = _aplicar_stride(
                    _rgb_a_bgr(muestras), src_w, src_h)
                del muestras

                self.progreso.emit(
                    base + 8,
                    f"Enviando página {num_pagina + 1} a la impresora…")
                self._imprimir_pagina(hdc, gdi32, handle, datos,
                                      src_w, src_h, caps.ancho_px, caps.alto_px)
                del datos
                return

            except (MemoryError, RuntimeError, ValueError) as e:
                ultimo_error = e
                log.warning("Página %d falló a %d DPI (%s)",
                            num_pagina + 1, dpi, e)
                if intento < len(dpis) - 1:
                    self.aviso.emit(
                        f"La impresora rechazó la página {num_pagina + 1} a "
                        f"{dpi} DPI; se reintenta con menor resolución.")

        raise RuntimeError(
            f"No se pudo imprimir la página {num_pagina + 1} ni siquiera a "
            f"{dpis[-1]} DPI.\n{ultimo_error}")

    @staticmethod
    def _imprimir_pagina(hdc, gdi32, handle, datos: bytes,
                         src_w: int, src_h: int,
                         page_px_w: int, page_px_h: int) -> None:
        """Escribe un bitmap BGR en el DC, centrado y a escala, como una
        página nueva del trabajo de impresión en curso."""
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
                    "StretchDIBits devolvió 0 — revisá el driver de la impresora.")
        finally:
            hdc.EndPage()


# ─────────────────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────────────────
class ImpresionPagina:

    @staticmethod
    def imprimir(ruta_pdf: str, paginas, parent=None) -> bool:
        """Muestra el diálogo de impresión e imprime las páginas indicadas.

        `paginas` es una lista de índices 0-based (también acepta un int
        suelto, por compatibilidad). Devuelve True si el trabajo se envió.
        """
        if isinstance(paginas, int):
            paginas = [paginas]
        paginas = sorted({int(p) for p in paginas})

        if not paginas:
            QMessageBox.warning(parent, "Sin páginas",
                                "No hay páginas seleccionadas para imprimir.")
            return False

        if not PYMUPDF_OK:
            QMessageBox.critical(
                parent, "Dependencia faltante",
                "PyMuPDF no está instalado.\n\npip install pymupdf")
            return False

        # Un único chequeo para "no hay Windows", "falta pywin32" y
        # "no hay ninguna impresora instalada", cada uno con su mensaje.
        try:
            verificar_impresion_disponible()
        except ErrorDispositivo as e:
            QMessageBox.critical(parent, "Impresión no disponible",
                                 e.texto_completo())
            return False

        etiqueta = formatear_paginas(paginas)

        # 1. Elegir impresora (Qt sólo para la UI, no para imprimir).
        #    La orientación se toma de la primera página elegida.
        printer_qt = QPrinter(QPrinter.PrinterMode.ScreenResolution)
        printer_qt.setColorMode(QPrinter.ColorMode.Color)
        try:
            with fitz.open(ruta_pdf) as doc_tmp:
                total_doc = doc_tmp.page_count
                fuera = [p for p in paginas if not 0 <= p < total_doc]
                if fuera:
                    QMessageBox.critical(
                        parent, "Páginas inexistentes",
                        f"El documento tiene {total_doc} página(s) y se pidieron: "
                        f"{formatear_paginas(fuera)}.")
                    return False
                rect = doc_tmp[paginas[0]].rect
                printer_qt.setPageOrientation(
                    QPrinter.Orientation.Landscape if rect.width > rect.height
                    else QPrinter.Orientation.Portrait)
        except Exception:
            pass

        dialog = QPrintDialog(printer_qt, parent)
        dialog.setWindowTitle(
            f"Imprimir — {len(paginas)} página(s): {etiqueta}")
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return False

        # 2. Render + impresión en segundo plano, con progreso visible
        progreso = QProgressDialog(
            f"Preparando {len(paginas)} página(s)…", "", 0, 100, parent)
        progreso.setWindowTitle("Imprimiendo")
        progreso.setCancelButton(None)          # el trabajo GDI no es cancelable
        progreso.setWindowModality(Qt.WindowModality.WindowModal)
        progreso.setMinimumDuration(0)
        progreso.setAutoClose(False)
        progreso.setValue(0)

        worker = _WorkerImpresion(ruta_pdf, paginas, printer_qt.printerName())
        errores: list[str] = []
        avisos: list[str] = []
        worker.progreso.connect(
            lambda pct, txt: (progreso.setValue(min(100, pct)),
                              progreso.setLabelText(txt)))
        worker.error.connect(errores.append)
        # Los avisos son problemas que no impidieron imprimir (driver que
        # informa mal, reintento a menor DPI): van al log, no a un cartel.
        worker.aviso.connect(lambda m: (avisos.append(m), log.warning(m)))
        worker.start()

        # Mantiene la UI viva sin anidar event loops propios.
        while not worker.wait(30):
            QApplication.processEvents()
        progreso.close()

        if errores or not worker.ok:
            detalle = errores[0] if errores else "La impresión no se completó."
            if worker.impresas:
                detalle += (f"\n\nSe alcanzaron a enviar {worker.impresas} "
                            f"de {len(paginas)} páginas.")
            QMessageBox.critical(parent, "Error de impresión",
                                 f"No se pudo imprimir:\n\n{detalle}")
            return False

        return True
