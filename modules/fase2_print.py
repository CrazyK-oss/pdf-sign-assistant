# modules/fase2_print.py
# Estrategia: bypass completo de QPrinter/GDI de Qt.
# Usamos win32print + win32ui (API nativa de Windows) para enviar
# el bitmap directamente al spooler, sin ninguna capa Qt en el medio.
#
# Flujo:
#   1. QPrintDialog de Qt para que el usuario elija impresora (solo UI)
#   2. fitz renderiza la página a RGB
#   3. PIL convierte a BMP en memoria
#   4. win32ui/win32print imprime el BMP directo al driver

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtWidgets import QMessageBox

try:
    import fitz
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

try:
    import win32print
    import win32ui
    import win32con
    from PIL import Image
    import io
    WIN32_OK = True
except ImportError:
    WIN32_OK = False

PRINT_DPI = 150


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
                "    pip install pywin32 pillow")
            return False

        # ── 1. Elegir impresora con el diálogo nativo de Qt (solo UI) ───
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
        dialog.setWindowTitle(f"Imprimir \u2014 P\u00e1gina {num_pagina + 1}")
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return False

        printer_name = printer_qt.printerName()

        # ── 2. Renderizar con fitz ────────────────────────────────────
        try:
            with fitz.open(ruta_pdf) as doc:
                pagina = doc[num_pagina]
                zoom   = PRINT_DPI / 72.0
                pix    = pagina.get_pixmap(
                    matrix=fitz.Matrix(zoom, zoom),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
        except Exception as e:
            QMessageBox.critical(parent, "Error al procesar el PDF",
                f"No se pudo renderizar la página:\n\n{e}")
            return False

        # ── 3. fitz pixmap -> PIL Image ───────────────────────────────
        pil_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        # ── 4. Imprimir con win32print directo ─────────────────────────
        try:
            ImpresionPagina._win32_print(printer_name, pil_img, PRINT_DPI)
        except Exception as e:
            QMessageBox.critical(parent, "Error de impresión",
                f"No se pudo imprimir:\n\n{e}")
            return False

        return True

    @staticmethod
    def _win32_print(printer_name: str, pil_img: "Image.Image", dpi: int):
        """Enviar PIL Image a la impresora usando win32ui (DC nativo)."""
        # Abrir el DC de la impresora
        hprinter = win32print.OpenPrinter(printer_name)
        try:
            printer_info = win32print.GetPrinter(hprinter, 2)
            devmode = printer_info["pDevMode"]
        finally:
            win32print.ClosePrinter(hprinter)

        # Crear Device Context de impresora
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)

        # Tamaño de la página en píxeles (según el driver)
        pw = hdc.GetDeviceCaps(win32con.HORZRES)
        ph = hdc.GetDeviceCaps(win32con.VERTRES)

        # Escalar imagen manteniendo proporción
        img_w, img_h = pil_img.size
        scale = min(pw / img_w, ph / img_h)
        dest_w = int(img_w * scale)
        dest_h = int(img_h * scale)
        x_off  = (pw - dest_w) // 2
        y_off  = (ph - dest_h) // 2

        # Redimensionar con Pillow (Lanczos = máxima calidad)
        pil_resized = pil_img.resize((dest_w, dest_h), Image.LANCZOS)

        # Convertir a BMP en memoria
        bmp_io = io.BytesIO()
        pil_resized.save(bmp_io, format="BMP")
        bmp_bytes = bmp_io.getvalue()

        # Crear HBITMAP desde los bytes
        import ctypes
        hbitmap = ctypes.windll.gdi32.CreateBitmap(
            dest_w, dest_h, 1, 24,
            ctypes.c_char_p(bytes(pil_resized.tobytes()))
        )

        # Iniciar documento
        hdc.StartDoc("PDF Print")
        hdc.StartPage()

        # Crear memory DC y seleccionar bitmap
        mdc = hdc.CreateCompatibleDC()
        mdc.SelectObject(win32ui.CreateBitmapFromHandle(hbitmap))

        # BitBlt: copiar del memory DC al printer DC
        hdc.BitBlt(
            (x_off, y_off), (dest_w, dest_h),
            mdc, (0, 0),
            win32con.SRCCOPY
        )

        hdc.EndPage()
        hdc.EndDoc()
        hdc.DeleteDC()
