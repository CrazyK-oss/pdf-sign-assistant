# modules/fase2_print.py
# Fase 2: Impresión de una página específica del PDF.
#
# ESTRATEGIA: win32print + pypdf.
#
# Por qué esta ruta:
#   - QPrinter.handle() no existe en PyQt6 => no podemos llamar SetICMMode.
#   - drawImage por GDI aplica el perfil ICC del driver HP => morado.
#   - Solución: saltamos GDI por completo y enviamos el PDF directamente
#     a la cola de impresión usando win32print con datatype "RAW" o
#     el proveedor de impresión de Windows para PDF (XPS/EMF).
#
# FLUJO:
#   1. Mostrar un QDialog simple para elegir impresora (combo con las
#      impresoras instaladas via win32print.EnumPrinters).
#   2. Extraer la página con pypdf a un PDF temporal.
#   3. Leer los bytes del PDF temporal.
#   4. Abrirlo con win32print usando datatype "RAW" directamente al spool.
#      El spooler de Windows procesa el PDF nativo => colores exactos,
#      cero intermediarios, cero ICM involuntario.
#
# REQUISITO: pip install pywin32

import os
import sys
import tempfile

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QMessageBox
)

try:
    from pypdf import PdfReader, PdfWriter
    PYPDF_OK = True
except ImportError:
    PYPDF_OK = False

try:
    import fitz
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

try:
    import win32print
    WIN32_OK = True
except ImportError:
    WIN32_OK = False


# ─────────────────────────────────────────────────────────────────────────
#  Diálogo de selección de impresora
# ─────────────────────────────────────────────────────────────────────────

class _DialogoImpresora(QDialog):
    """Diálogo minimalista para elegir impresora instalada."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Imprimir")
        self.setMinimumWidth(360)
        self.impresora_elegida: str | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        layout.addWidget(QLabel("Impresora:"))

        self._combo = QComboBox()
        impresoras = [p[2] for p in win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        )]
        default = win32print.GetDefaultPrinter()
        self._combo.addItems(impresoras)
        if default in impresoras:
            self._combo.setCurrentText(default)
        layout.addWidget(self._combo)

        btns = QHBoxLayout()
        btn_ok     = QPushButton("Imprimir")
        btn_cancel = QPushButton("Cancelar")
        btn_ok.setDefault(True)
        btns.addStretch()
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

        btn_ok.clicked.connect(self._aceptar)
        btn_cancel.clicked.connect(self.reject)

    def _aceptar(self):
        self.impresora_elegida = self._combo.currentText()
        self.accept()


# ─────────────────────────────────────────────────────────────────────────
#  Extracción de página
# ─────────────────────────────────────────────────────────────────────────

def _extraer_pagina(ruta_pdf: str, num_pagina: int) -> bytes | None:
    """Extrae la página como bytes de PDF de 1 hoja."""
    if PYPDF_OK:
        try:
            reader = PdfReader(ruta_pdf)
            writer = PdfWriter()
            writer.add_page(reader.pages[num_pagina])
            import io
            buf = io.BytesIO()
            writer.write(buf)
            return buf.getvalue()
        except Exception:
            pass

    if PYMUPDF_OK:
        try:
            import io
            src = fitz.open(ruta_pdf)
            dst = fitz.open()
            dst.insert_pdf(src, from_page=num_pagina, to_page=num_pagina)
            buf = io.BytesIO()
            dst.save(buf)
            dst.close()
            src.close()
            return buf.getvalue()
        except Exception:
            pass

    return None


# ─────────────────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────────────────

class ImpresionPagina:

    @staticmethod
    def imprimir(ruta_pdf: str, num_pagina: int, parent=None) -> bool:
        """
        Imprime la página usando win32print (RAW spool directo).
        Sin GDI, sin ICM, sin QPrinter => colores exactos.
        """
        if not WIN32_OK:
            QMessageBox.critical(
                parent, "Dependencia faltante",
                "Se necesita pywin32 para imprimir.\n\n"
                "Instálalo con:\n    pip install pywin32"
            )
            return False

        if not PYPDF_OK and not PYMUPDF_OK:
            QMessageBox.critical(
                parent, "Dependencia faltante",
                "Se necesita pypdf o PyMuPDF para imprimir.\n\n"
                "Instálalo con:\n    pip install pypdf"
            )
            return False

        # ── 1. Elegir impresora ──────────────────────────────────────────
        dlg = _DialogoImpresora(parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        nombre_impresora = dlg.impresora_elegida

        # ── 2. Extraer página como bytes PDF ──────────────────────────────
        pdf_bytes = _extraer_pagina(ruta_pdf, num_pagina)
        if not pdf_bytes:
            QMessageBox.critical(
                parent, "Error al preparar impresión",
                "No se pudo extraer la página del PDF."
            )
            return False

        # ── 3. Enviar al spooler con win32print RAW ────────────────────────
        #
        # Datatype "RAW": el spooler de Windows pasa los bytes directamente
        # al driver sin ningún procesamiento GDI/ICM adicional.
        # El driver HP Smart Tank 530 acepta RAW PDF via su filtro XPS.
        try:
            hprinter = win32print.OpenPrinter(nombre_impresora)
            try:
                win32print.StartDocPrinter(
                    hprinter, 1,
                    (f"PDF-Sign-Assistant pág {num_pagina + 1}", None, "RAW")
                )
                win32print.StartPagePrinter(hprinter)
                win32print.WritePrinter(hprinter, pdf_bytes)
                win32print.EndPagePrinter(hprinter)
                win32print.EndDocPrinter(hprinter)
            finally:
                win32print.ClosePrinter(hprinter)
            return True
        except Exception as e:
            QMessageBox.critical(
                parent, "Error de impresión",
                f"No se pudo enviar a la impresora:\n\n{e}"
            )
            return False
