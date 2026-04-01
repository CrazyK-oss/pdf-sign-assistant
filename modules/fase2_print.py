# modules/fase2_print.py
# Estrategia definitiva: renderizar el PDF a alta resolución con fitz,
# luego enviarlo a la impresora usando StretchDIBits() directamente sobre
# el printer DC. Esto evita:
#   - El pipeline GDI/ICM que convierte colores (fuente del morado)
#   - La limitación de 150 DPI del render anterior (fuente de la baja calidad)
#   - CreateBitmap/SelectObject que fallaba con "Select bitmap object failed"
#   - ImageWin.Dib que pasaba por GDI y seguía tocando el color
#
# StretchDIBits escribe píxeles BGR directamente en el DC de la impresora,
# sin que ninguna capa intermedia (ICM, GDI+, Qt) los transforme.

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtWidgets import QMessageBox
import ctypes
import ctypes.wintypes
import struct

try:
    import fitz
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

try:
    import win32print
    import win32ui
    import win32con
    WIN32_OK = True
except ImportError:
    WIN32_OK = False

# DPI del render: usamos el DPI real del printer DC para resolución máxima,
# pero lo capamos a 300 para evitar imágenes enormes en memoria.
MAX_RENDER_DPI = 300


class ImpresionPagina:

    @staticmethod
    def imprimir(ruta_pdf: str, num_pagina: int, parent=None) -> bool:
        if not PYMUPDF_OK:
            QMessageBox.critical(parent, "Dependencia faltante",
                "PyMuPDF no está instalado.\npip install pymupdf")
            return False

        if not WIN32_OK:
            QMessageBox.critical(parent, "Dependencia faltante",
                "Faltan dependencias para imprimir.\n\n"
                "Instálalas con:\n"
                "    pip install pywin32")
            return False

        # 1. Elegir impresora (Qt solo para UI, no para imprimir)
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

        printer_name = printer_qt.printerName()

        # 2. Abrir printer DC para conocer DPI real y resolución de página
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)
        try:
            printer_dpi_x = hdc.GetDeviceCaps(win32con.LOGPIXELSX)
            printer_dpi_y = hdc.GetDeviceCaps(win32con.LOGPIXELSY)
            page_px_w    = hdc.GetDeviceCaps(win32con.HORZRES)
            page_px_h    = hdc.GetDeviceCaps(win32con.VERTRES)
        finally:
            hdc.DeleteDC()

        render_dpi = min(max(printer_dpi_x, printer_dpi_y), MAX_RENDER_DPI)

        # 3. Renderizar PDF a la resolución del render_dpi
        try:
            with fitz.open(ruta_pdf) as doc:
                pagina = doc[num_pagina]
                zoom = render_dpi / 72.0
                pix = pagina.get_pixmap(
                    matrix=fitz.Matrix(zoom, zoom),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
        except Exception as e:
            QMessageBox.critical(parent, "Error al procesar el PDF",
                f"No se pudo renderizar la página:\n\n{e}")
            return False

        # 4. Imprimir vía StretchDIBits directo al printer DC
        try:
            ImpresionPagina._stretch_dibits_print(
                printer_name, pix, page_px_w, page_px_h
            )
        except Exception as e:
            QMessageBox.critical(parent, "Error de impresión",
                f"No se pudo imprimir:\n\n{e}")
            return False

        return True

    @staticmethod
    def _stretch_dibits_print(
        printer_name: str,
        pix: "fitz.Pixmap",
        page_px_w: int,
        page_px_h: int,
    ):
        """
        Envía el pixmap de fitz a la impresora con StretchDIBits.

        fitz entrega RGB (R, G, B) por byte; GDI espera BGR por byte.
        Hacemos el swap aquí para que los colores sean exactos y sin
        ninguna capa de gestión de color en el camino.
        """
        src_w = pix.width
        src_h = pix.height

        # Swap R<->B para pasar de RGB (fitz) a BGR (GDI)
        rgb_bytes = bytearray(pix.samples)
        for i in range(0, len(rgb_bytes), 3):
            rgb_bytes[i], rgb_bytes[i + 2] = rgb_bytes[i + 2], rgb_bytes[i]

        # Stride en GDI debe ser múltiplo de 4 bytes
        stride = ((src_w * 3) + 3) & ~3
        if stride == src_w * 3:
            bgr_data = bytes(rgb_bytes)
        else:
            # Rellenar cada fila al stride correcto
            row_bytes = src_w * 3
            padded = bytearray(stride * src_h)
            for row in range(src_h):
                src_start = row * row_bytes
                dst_start = row * stride
                padded[dst_start:dst_start + row_bytes] = \
                    rgb_bytes[src_start:src_start + row_bytes]
            bgr_data = bytes(padded)

        # BITMAPINFOHEADER (40 bytes)
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

        # Escalar manteniendo proporción centrada
        scale   = min(page_px_w / src_w, page_px_h / src_h)
        dest_w  = max(1, int(src_w * scale))
        dest_h  = max(1, int(src_h * scale))
        x_off   = (page_px_w - dest_w) // 2
        y_off   = (page_px_h - dest_h) // 2

        gdi32 = ctypes.windll.gdi32
        SRCCOPY        = 0x00CC0020
        DIB_RGB_COLORS = 0
        HALFTONE       = 4  # SetStretchBltMode para máxima calidad

        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)
        hdc_handle = hdc.GetHandleOutput()

        gdi32.SetStretchBltMode(hdc_handle, HALFTONE)

        hdc.StartDoc("PDF Print")
        hdc.StartPage()
        try:
            # StretchDIBits(hdc, xDest, yDest, nDestWidth, nDestHeight,
            #               xSrc, ySrc, nSrcWidth, nSrcHeight,
            #               lpBits, lpBitsInfo, iUsage, dwRop)
            result = gdi32.StretchDIBits(
                hdc_handle,
                x_off, y_off, dest_w, dest_h,
                0, 0, src_w, src_h,
                bgr_data,
                bmi,
                DIB_RGB_COLORS,
                SRCCOPY,
            )
            if result == 0:
                raise RuntimeError("StretchDIBits retornó 0 — verifique el driver de la impresora.")
        finally:
            hdc.EndPage()
            hdc.EndDoc()
            hdc.DeleteDC()
