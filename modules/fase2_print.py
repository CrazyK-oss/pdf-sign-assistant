# modules/fase2_print.py
# Estrategia: bypass completo de QPrinter/GDI de Qt para render.
# Usamos win32print + win32ui (API nativa de Windows) solo para elegir
# impresora y dibujar un DIB estable de 32 bits, evitando CreateBitmap()
# con memoria RGB cruda que puede fallar con "Select bitmap object failed".

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
    from PIL import Image, ImageWin
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

        try:
            with fitz.open(ruta_pdf) as doc:
                pagina = doc[num_pagina]
                zoom = PRINT_DPI / 72.0
                pix = pagina.get_pixmap(
                    matrix=fitz.Matrix(zoom, zoom),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
        except Exception as e:
            QMessageBox.critical(parent, "Error al procesar el PDF",
                f"No se pudo renderizar la página:\n\n{e}")
            return False

        pil_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        try:
            ImpresionPagina._win32_print(printer_name, pil_img)
        except Exception as e:
            QMessageBox.critical(parent, "Error de impresión",
                f"No se pudo imprimir:\n\n{e}")
            return False

        return True

    @staticmethod
    def _win32_print(printer_name: str, pil_img: "Image.Image"):
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)
        try:
            pw = hdc.GetDeviceCaps(win32con.HORZRES)
            ph = hdc.GetDeviceCaps(win32con.VERTRES)

            img_w, img_h = pil_img.size
            scale = min(pw / img_w, ph / img_h)
            dest_w = max(1, int(img_w * scale))
            dest_h = max(1, int(img_h * scale))
            x_off = (pw - dest_w) // 2
            y_off = (ph - dest_h) // 2

            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            pil_resized = pil_img.resize((dest_w, dest_h), Image.LANCZOS)

            dib = ImageWin.Dib(pil_resized)

            hdc.StartDoc("PDF Print")
            try:
                hdc.StartPage()
                try:
                    dib.draw(hdc.GetHandleOutput(), (x_off, y_off, x_off + dest_w, y_off + dest_h))
                finally:
                    hdc.EndPage()
            finally:
                hdc.EndDoc()
        finally:
            hdc.DeleteDC()
