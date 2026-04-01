# modules/fase2_print.py
# Fase 2: Impresión de una página específica del PDF.
#
# ESTRATEGIA: delegar la impresión al visor PDF nativo del sistema.
#
# Por qué abandoné QPrinter / QPainter:
#   - QPrinter.handle() fue eliminado en PyQt6 (no existe).
#   - Todas las rutas de drawImage/drawPixmap sobre QPrinter en Windows
#     pasan por GDI, que aplica el perfil ICC del driver HP Smart Tank
#     y desplaza los colores (morado, café). No hay forma de desactivarlo
#     desde PyQt6 porque handle() ya no está disponible.
#
# SOLUCIÓN: os.startfile(ruta_pdf, "print")
#   Windows asocia el verbo "print" al visor PDF predeterminado (Adobe,
#   Edge, SumatraPDF, Foxit, etc.). Ese visor:
#     1. Abre el PDF.
#     2. Envía la página a la impresora usando su propio pipeline nativo.
#     3. Gestiona el perfil de color correctamente.
#     4. Cierra solo en segundo plano.
#   Resultado: colores exactos, sin morado, sin ningún procesamiento
#   intermedio nuestro.
#
# LIMITACIÓN: no podemos filtrar a una sola página con este verbo,
# así que extraemos la página a un PDF temporal de 1 hoja y lo imprimimos.
# El temporal se borra automáticamente al salir del proceso (tempfile).

import os
import sys
import tempfile
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

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


def _extraer_pagina(ruta_pdf: str, num_pagina: int) -> str | None:
    """
    Extrae una sola página a un PDF temporal y devuelve su ruta.
    Intenta primero con pypdf, luego con fitz como fallback.
    Devuelve None si ninguno está disponible.
    """
    if PYPDF_OK:
        try:
            reader = PdfReader(ruta_pdf)
            writer = PdfWriter()
            writer.add_page(reader.pages[num_pagina])
            tmp = tempfile.NamedTemporaryFile(
                suffix=".pdf", delete=False, prefix="psa_print_"
            )
            writer.write(tmp)
            tmp.close()
            return tmp.name
        except Exception:
            pass

    if PYMUPDF_OK:
        try:
            src = fitz.open(ruta_pdf)
            dst = fitz.open()
            dst.insert_pdf(src, from_page=num_pagina, to_page=num_pagina)
            tmp = tempfile.NamedTemporaryFile(
                suffix=".pdf", delete=False, prefix="psa_print_"
            )
            dst.save(tmp.name)
            dst.close()
            src.close()
            tmp.close()
            return tmp.name
        except Exception:
            pass

    return None


class ImpresionPagina:

    @staticmethod
    def imprimir(ruta_pdf: str, num_pagina: int, parent=None) -> bool:
        """
        Imprime la página indicada del PDF usando el visor nativo del OS.
        Extrae la página a un temporal y usa os.startfile con verbo 'print'.

        Returns True si se envió a imprimir, False si el usuario canceló
        o hubo un error.
        """
        if not PYPDF_OK and not PYMUPDF_OK:
            QMessageBox.critical(
                parent,
                "Dependencia faltante",
                "Se necesita pypdf o PyMuPDF para imprimir.\n\n"
                "Instálalo con:\n    pip install pypdf"
            )
            return False

        if sys.platform != "win32":
            QMessageBox.warning(
                parent,
                "Plataforma no soportada",
                "La impresión nativa solo está disponible en Windows."
            )
            return False

        # Extraer la página a un PDF temporal de 1 hoja
        ruta_tmp = _extraer_pagina(ruta_pdf, num_pagina)
        if not ruta_tmp:
            QMessageBox.critical(
                parent,
                "Error al preparar impresión",
                "No se pudo extraer la página del PDF.\n"
                "Verificá que el archivo no esté protegido."
            )
            return False

        # Enviar al visor PDF predeterminado con verbo 'print'
        # El visor abre el diálogo de impresión nativo con todos los colores
        # correctos y se cierra solo en segundo plano.
        try:
            os.startfile(ruta_tmp, "print")
            return True
        except Exception as e:
            QMessageBox.critical(
                parent,
                "Error de impresión",
                f"No se pudo abrir el visor PDF para imprimir:\n\n{e}\n\n"
                "Verificá que haya un visor de PDF instalado (Edge, Adobe, SumatraPDF)."
            )
            return False
