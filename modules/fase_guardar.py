"""
modules/fase_guardar.py
=======================
Fase 4 del flujo principal: confirmación y guardado del PDF modificado.

Recibe:
  - ruta_pdf    : Path del PDF de trabajo (en pdfs_trabajo/)
  - ruta_imagen : str  ruta de la imagen escaneada (PNG/BMP/JPG)
  - num_pagina  : int  índice 0-based de la página a reemplazar

Emite:
  - guardado_listo(Path)  → ruta del PDF final guardado en pdfs_firmados/
  - cancelado()           → el usuario descartó la operación
"""

import os
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QMessageBox, QSizePolicy, QSpacerItem,
)


# ─────────────────────────────────────────────────────────────────────────
#  Worker: convierte imagen → página PDF y reemplaza en hilo secundario
# ─────────────────────────────────────────────────────────────────────────
class _WorkerGuardar(QThread):
    listo = pyqtSignal(str)   # ruta del PDF final
    error = pyqtSignal(str)

    def __init__(self, ruta_pdf: Path, ruta_imagen: str,
                 num_pagina: int, destino: Path, parent=None):
        super().__init__(parent)
        self._ruta_pdf    = ruta_pdf
        self._ruta_imagen = ruta_imagen
        self._num_pagina  = num_pagina
        self._destino     = destino

    def run(self):
        try:
            # ── 1. Convertir imagen a PDF de una sola página ──────────
            try:
                import img2pdf
                with open(self._ruta_imagen, "rb") as f_img:
                    datos_pdf = img2pdf.convert(f_img)
                tmp_pag = tempfile.NamedTemporaryFile(
                    suffix=".pdf", delete=False
                )
                tmp_pag.write(datos_pdf)
                tmp_pag.close()
                ruta_pag_pdf = tmp_pag.name
            except ImportError:
                # Fallback: usar pypdf + Pillow si img2pdf no está
                from PIL import Image
                img = Image.open(self._ruta_imagen)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                tmp_pag = tempfile.NamedTemporaryFile(
                    suffix=".pdf", delete=False
                )
                tmp_pag.close()
                img.save(tmp_pag.name, "PDF", resolution=150)
                ruta_pag_pdf = tmp_pag.name

            # ── 2. Reemplazar la página en el PDF original ────────────
            try:
                from pypdf import PdfReader, PdfWriter
            except ImportError:
                from PyPDF2 import PdfReader, PdfWriter

            lector_orig  = PdfReader(str(self._ruta_pdf))
            lector_nueva = PdfReader(ruta_pag_pdf)
            writer = PdfWriter()

            for i, pag in enumerate(lector_orig.pages):
                if i == self._num_pagina:
                    # Escalar la nueva página al tamaño original
                    pag_nueva = lector_nueva.pages[0]
                    pag_nueva.mediabox = pag.mediabox
                    writer.add_page(pag_nueva)
                else:
                    writer.add_page(pag)

            with open(self._destino, "wb") as f_out:
                writer.write(f_out)

            # ── 3. Limpiar temporal ───────────────────────────────────
            try:
                os.remove(ruta_pag_pdf)
            except Exception:
                pass

            self.listo.emit(str(self._destino))

        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────────────────
#  Widget principal de la Fase 4
# ─────────────────────────────────────────────────────────────────────────
class FaseGuardar(QWidget):
    """
    Pantalla de confirmación y guardado del documento modificado.

    Señales:
      guardado_listo(Path)  → PDF guardado correctamente
      cancelado()           → usuario canceló
    """
    guardado_listo = pyqtSignal(object)   # Path
    cancelado      = pyqtSignal()

    def __init__(self, ruta_pdf: Path, ruta_imagen: str,
                 num_pagina: int, carpeta_firmados: Path, parent=None):
        super().__init__(parent)
        self._ruta_pdf        = ruta_pdf
        self._ruta_imagen     = ruta_imagen
        self._num_pagina      = num_pagina
        self._carpeta_firmados = carpeta_firmados
        self._worker: _WorkerGuardar | None = None
        self._construir_ui()

    # ── UI ────────────────────────────────────────────────────────────
    def _construir_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        # Cabecera
        cab = QFrame()
        cab.setFixedHeight(64)
        cab.setStyleSheet("""
            QFrame {
                background: #f3f0ec;
                border-bottom: 1px solid rgba(40,37,29,0.10);
            }
        """)
        lay_cab = QHBoxLayout(cab)
        lay_cab.setContentsMargins(20, 0, 20, 0)

        nombre_pdf = os.path.basename(str(self._ruta_pdf))
        lbl_titulo = QLabel(
            f"Guardar  ·  Página {self._num_pagina + 1}  ·  {nombre_pdf}"
        )
        font_cab = QFont("Segoe UI", 13)
        font_cab.setWeight(QFont.Weight.Medium)
        lbl_titulo.setFont(font_cab)
        lbl_titulo.setStyleSheet("color: #28251d;")
        lay_cab.addWidget(lbl_titulo)

        lay_cab.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Minimum)
        )

        btn_volver = QPushButton("← Volver al escaneo")
        btn_volver.setFixedHeight(36)
        btn_volver.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #7a7974;
                border: 1px solid rgba(40,37,29,0.22);
                border-radius: 6px;
                padding: 0 16px;
                font-size: 13px;
            }
            QPushButton:hover { color: #28251d; border-color: rgba(40,37,29,0.45); }
        """)
        btn_volver.clicked.connect(self.cancelado)
        lay_cab.addWidget(btn_volver)
        raiz.addWidget(cab)

        # Cuerpo
        cuerpo = QWidget()
        cuerpo.setStyleSheet("background: #f7f6f2;")
        lay_cuerpo = QVBoxLayout(cuerpo)
        lay_cuerpo.setContentsMargins(40, 28, 40, 28)
        lay_cuerpo.setSpacing(20)

        # ── Preview de la imagen ──────────────────────────────────────
        panel_prev = QFrame()
        panel_prev.setStyleSheet("""
            QFrame {
                background: #f9f8f5;
                border: 1px solid rgba(1,105,111,0.25);
                border-radius: 10px;
            }
        """)
        lay_prev = QHBoxLayout(panel_prev)
        lay_prev.setContentsMargins(16, 16, 16, 16)
        lay_prev.setSpacing(16)

        self.lbl_img = QLabel()
        self.lbl_img.setFixedSize(90, 118)
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_img.setStyleSheet("background: #edeae5; border-radius: 4px;")
        self._cargar_preview()
        lay_prev.addWidget(self.lbl_img)

        info_col = QVBoxLayout()
        info_col.setSpacing(4)

        lbl_tag = QLabel("IMAGEN ESCANEADA")
        lbl_tag.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #7a7974;"
            "letter-spacing: 1px;"
        )
        info_col.addWidget(lbl_tag)

        lbl_nombre_img = QLabel(os.path.basename(self._ruta_imagen))
        font_n = QFont("Segoe UI", 12)
        font_n.setWeight(QFont.Weight.Medium)
        lbl_nombre_img.setFont(font_n)
        lbl_nombre_img.setStyleSheet("color: #28251d;")
        info_col.addWidget(lbl_nombre_img)

        lbl_ruta_img = QLabel(self._ruta_imagen)
        lbl_ruta_img.setStyleSheet("color: #7a7974; font-size: 11px;")
        lbl_ruta_img.setWordWrap(True)
        info_col.addWidget(lbl_ruta_img)

        info_col.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Minimum,
                        QSizePolicy.Policy.Expanding)
        )
        lay_prev.addLayout(info_col)
        lay_cuerpo.addWidget(panel_prev)

        # ── Campo nombre del archivo ──────────────────────────────────
        panel_nombre = QFrame()
        panel_nombre.setStyleSheet("""
            QFrame {
                background: #f9f8f5;
                border: 1px solid rgba(40,37,29,0.10);
                border-radius: 10px;
            }
        """)
        lay_nombre = QVBoxLayout(panel_nombre)
        lay_nombre.setContentsMargins(20, 18, 20, 18)
        lay_nombre.setSpacing(8)

        lbl_campo = QLabel("Nombre del documento a guardar")
        font_h = QFont("Segoe UI", 12)
        font_h.setWeight(QFont.Weight.Medium)
        lbl_campo.setFont(font_h)
        lbl_campo.setStyleSheet("color: #28251d;")
        lay_nombre.addWidget(lbl_campo)

        lbl_sub = QLabel(
            "El archivo se guardará en la carpeta pdfs_firmados/ con este nombre."
        )
        lbl_sub.setStyleSheet("color: #7a7974; font-size: 12px;")
        lay_nombre.addWidget(lbl_sub)

        fila_input = QHBoxLayout()
        fila_input.setSpacing(8)

        self.input_nombre = QLineEdit()
        self.input_nombre.setFixedHeight(38)
        self.input_nombre.setPlaceholderText("ej: contrato_firmado")
        self.input_nombre.setStyleSheet("""
            QLineEdit {
                background: white;
                border: 1px solid rgba(40,37,29,0.22);
                border-radius: 6px;
                padding: 0 12px;
                font-size: 13px;
                color: #28251d;
            }
            QLineEdit:focus {
                border: 1.5px solid #01696f;
            }
        """)
        # Sugerir nombre basado en el PDF original
        stem = Path(str(self._ruta_pdf)).stem
        # Quitar prefijos de re-edición si los hay
        if stem.startswith("reedit_"):
            stem = stem[len("reedit_"):]
        self.input_nombre.setText(stem)
        self.input_nombre.selectAll()
        fila_input.addWidget(self.input_nombre)

        lbl_ext = QLabel(".pdf")
        lbl_ext.setStyleSheet("color: #7a7974; font-size: 13px;")
        fila_input.addWidget(lbl_ext)
        lay_nombre.addLayout(fila_input)

        self.lbl_error_nombre = QLabel("")
        self.lbl_error_nombre.setStyleSheet(
            "color: #a13544; font-size: 12px;"
        )
        self.lbl_error_nombre.hide()
        lay_nombre.addWidget(self.lbl_error_nombre)

        lay_cuerpo.addWidget(panel_nombre)
        lay_cuerpo.addStretch()

        raiz.addWidget(cuerpo, 1)
        raiz.addWidget(self._barra_inferior())

    def _cargar_preview(self):
        pm = QPixmap(self._ruta_imagen)
        if not pm.isNull():
            self.lbl_img.setPixmap(
                pm.scaled(
                    90, 118,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _barra_inferior(self) -> QFrame:
        barra = QFrame()
        barra.setFixedHeight(64)
        barra.setStyleSheet("""
            QFrame {
                background: #f9f8f5;
                border-top: 1px solid rgba(40,37,29,0.10);
            }
        """)
        lay = QHBoxLayout(barra)
        lay.setContentsMargins(20, 0, 20, 0)

        self.lbl_estado = QLabel("Revisá el nombre y confirmá para guardar.")
        self.lbl_estado.setStyleSheet("color: #7a7974; font-size: 13px;")
        lay.addWidget(self.lbl_estado)

        lay.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Minimum)
        )

        self.btn_guardar = QPushButton("Guardar documento  ✓")
        self.btn_guardar.setFixedHeight(40)
        self.btn_guardar.setStyleSheet("""
            QPushButton {
                background: #437a22;
                color: white;
                border: none;
                border-radius: 7px;
                padding: 0 22px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover   { background: #2e5c10; }
            QPushButton:pressed { background: #1e3f0a; }
            QPushButton:disabled { background: #dcd9d5; color: #bab9b4; }
        """)
        self.btn_guardar.clicked.connect(self._on_guardar)
        lay.addWidget(self.btn_guardar)

        return barra

    # ── Lógica de guardado ────────────────────────────────────────────
    def _on_guardar(self):
        nombre = self.input_nombre.text().strip()
        if not nombre:
            self.lbl_error_nombre.setText("El nombre no puede estar vacío.")
            self.lbl_error_nombre.show()
            self.input_nombre.setFocus()
            return

        # Limpiar caracteres inválidos en nombres de archivo
        caracteres_invalidos = set('/\\:*?"<>|')
        if any(c in nombre for c in caracteres_invalidos):
            self.lbl_error_nombre.setText(
                'El nombre no puede contener: / \\ : * ? " < > |'
            )
            self.lbl_error_nombre.show()
            return

        self.lbl_error_nombre.hide()

        if not nombre.lower().endswith(".pdf"):
            nombre += ".pdf"

        destino = self._carpeta_firmados / nombre

        # Avisar si ya existe y confirmar sobreescritura
        if destino.exists():
            resp = QMessageBox.question(
                self,
                "Archivo existente",
                f"Ya existe un archivo con ese nombre:\n{nombre}\n\n"
                "¿Querés reemplazarlo?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return

        self._set_guardando(True)

        self._worker = _WorkerGuardar(
            self._ruta_pdf,
            self._ruta_imagen,
            self._num_pagina,
            destino,
            parent=self,
        )
        self._worker.listo.connect(self._on_listo)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _set_guardando(self, guardando: bool):
        self.btn_guardar.setEnabled(not guardando)
        self.input_nombre.setEnabled(not guardando)
        if guardando:
            self.btn_guardar.setText("Guardando…")
            self.lbl_estado.setText("Procesando PDF, un momento…")
            self.lbl_estado.setStyleSheet(
                "color: #01696f; font-size: 13px; font-weight: 600;"
            )
        else:
            self.btn_guardar.setText("Guardar documento  ✓")
            self.lbl_estado.setText("Revisá el nombre y confirmá para guardar.")
            self.lbl_estado.setStyleSheet("color: #7a7974; font-size: 13px;")

    def _on_listo(self, ruta_str: str):
        self._set_guardando(False)
        self.guardado_listo.emit(Path(ruta_str))

    def _on_error(self, mensaje: str):
        self._set_guardando(False)
        QMessageBox.critical(
            self,
            "Error al guardar",
            f"No se pudo guardar el documento:\n\n{mensaje}\n\n"
            "Verificá que pypdf (o PyPDF2) y Pillow estén instalados."
        )
