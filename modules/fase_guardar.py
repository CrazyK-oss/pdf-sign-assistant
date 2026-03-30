"""
modules/fase_guardar.py
=======================
Fase 4 del flujo principal: confirmación y guardado del PDF modificado.

Recibe:
  - ruta_pdf    : Path del PDF de trabajo (en pdfs_trabajo/)
  - ruta_imagen : str  ruta de la imagen resultante (PNG/BMP/JPG)
                       sin importar si vino del escáner manual o de
                       drag-and-drop; el tratamiento es idéntico.
  - num_pagina  : int  índice 0-based de la página a reemplazar

Emite:
  - guardado_listo(Path)  → ruta del PDF final guardado en pdfs_firmados/
  - cancelado()           → el usuario descartó la operación

Cambios respecto a la versión anterior
---------------------------------------
* Barra de progreso real con 4 etapas reportadas por el worker.
* Worker emite señal `progreso(int, str)` para feedback granular.
* El nombre de destino se pre-rellena con el stem del PDF original
  (sin prefijo reedit_) y el usuario puede cambiarlo antes de guardar.
* Se eliminó la dependencia de QMessageBox para el estado "Guardando";
  ahora la barra de progreso + etiqueta dan feedback visual suficiente.
* Unificación total: no importa el origen de ruta_imagen, el flujo
  de conversión → reemplazo de página → escritura es el mismo.
"""

import os
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QMessageBox, QSizePolicy, QSpacerItem,
    QProgressBar,
)


# ─────────────────────────────────────────────────────────────────────────
#  Worker: convierte imagen → página PDF y reemplaza en hilo secundario
#  Emite progreso en 4 etapas (0-25-60-90-100 %)
# ─────────────────────────────────────────────────────────────────────────
class _WorkerGuardar(QThread):
    progreso = pyqtSignal(int, str)   # (porcentaje 0-100, etiqueta)
    listo    = pyqtSignal(str)        # ruta del PDF final
    error    = pyqtSignal(str)

    def __init__(self, ruta_pdf: Path, ruta_imagen: str,
                 num_pagina: int, destino: Path, parent=None):
        super().__init__(parent)
        self._ruta_pdf    = ruta_pdf
        self._ruta_imagen = ruta_imagen
        self._num_pagina  = num_pagina
        self._destino     = destino

    def run(self):
        ruta_pag_pdf: str | None = None
        try:
            # ── Etapa 1 / 4: Convertir imagen a PDF de una sola página ──
            self.progreso.emit(10, "Convirtiendo imagen a PDF…")
            try:
                import img2pdf
                with open(self._ruta_imagen, "rb") as f_img:
                    datos_pdf = img2pdf.convert(f_img)
                tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                tmp.write(datos_pdf)
                tmp.close()
                ruta_pag_pdf = tmp.name
            except ImportError:
                # Fallback: Pillow si img2pdf no está instalado
                from PIL import Image
                img = Image.open(self._ruta_imagen)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                tmp.close()
                img.save(tmp.name, "PDF", resolution=150)
                ruta_pag_pdf = tmp.name

            # ── Etapa 2 / 4: Abrir el PDF original ──────────────────────
            self.progreso.emit(35, "Leyendo documento original…")
            try:
                from pypdf import PdfReader, PdfWriter
            except ImportError:
                from PyPDF2 import PdfReader, PdfWriter

            lector_orig  = PdfReader(str(self._ruta_pdf))
            lector_nueva = PdfReader(ruta_pag_pdf)

            # ── Etapa 3 / 4: Reemplazar la página seleccionada ──────────
            self.progreso.emit(60, "Reemplazando página…")
            writer = PdfWriter()
            for i, pag in enumerate(lector_orig.pages):
                if i == self._num_pagina:
                    pag_nueva = lector_nueva.pages[0]
                    # Respetar el tamaño de la página original
                    pag_nueva.mediabox = pag.mediabox
                    writer.add_page(pag_nueva)
                else:
                    writer.add_page(pag)

            # ── Etapa 4 / 4: Escribir el PDF resultante ─────────────────
            self.progreso.emit(85, "Escribiendo archivo final…")
            with open(self._destino, "wb") as f_out:
                writer.write(f_out)

            # Limpieza del temporal
            try:
                os.remove(ruta_pag_pdf)
            except Exception:
                pass

            self.progreso.emit(100, "¡Listo!")
            self.listo.emit(str(self._destino))

        except Exception as e:
            # Limpiar temporal si algo falló a mitad
            if ruta_pag_pdf:
                try:
                    os.remove(ruta_pag_pdf)
                except Exception:
                    pass
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────────────────
#  Widget principal de la Fase 4
# ─────────────────────────────────────────────────────────────────────────
class FaseGuardar(QWidget):
    """
    Pantalla de confirmación y guardado del documento modificado.

    Acepta ruta_imagen de cualquier origen (escáner manual o drag-and-drop).
    Muestra barra de progreso real durante la conversión y guardado.

    Señales:
      guardado_listo(Path)  → PDF guardado correctamente
      cancelado()           → usuario canceló
    """
    guardado_listo = pyqtSignal(object)   # Path
    cancelado      = pyqtSignal()

    def __init__(self, ruta_pdf: Path, ruta_imagen: str,
                 num_pagina: int, carpeta_firmados: Path, parent=None):
        super().__init__(parent)
        self._ruta_pdf         = ruta_pdf
        self._ruta_imagen      = ruta_imagen
        self._num_pagina       = num_pagina
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

        self.btn_volver = QPushButton("← Volver al escaneo")
        self.btn_volver.setFixedHeight(36)
        self.btn_volver.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #7a7974;
                border: 1px solid rgba(40,37,29,0.22);
                border-radius: 6px;
                padding: 0 16px;
                font-size: 13px;
            }
            QPushButton:hover { color: #28251d; border-color: rgba(40,37,29,0.45); }
            QPushButton:disabled { color: #bab9b4; border-color: rgba(40,37,29,0.10); }
        """)
        self.btn_volver.clicked.connect(self.cancelado)
        lay_cab.addWidget(self.btn_volver)
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

        lbl_tag = QLabel("IMAGEN A INSERTAR")
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

        lbl_info_reemplazo = QLabel(
            f"Esta imagen reemplazará la página {self._num_pagina + 1} del documento."
        )
        lbl_info_reemplazo.setStyleSheet(
            "color: #01696f; font-size: 12px; font-weight: 600;"
        )
        info_col.addWidget(lbl_info_reemplazo)

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
            QLineEdit:disabled {
                background: #f3f0ec;
                color: #bab9b4;
            }
        """)
        # Nombre por defecto = stem del PDF original (sin prefijo reedit_)
        stem = Path(str(self._ruta_pdf)).stem
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

        # ── Barra de progreso (oculta hasta que inicia el guardado) ───
        self.panel_progreso = QFrame()
        self.panel_progreso.setStyleSheet("""
            QFrame {
                background: #f9f8f5;
                border: 1px solid rgba(1,105,111,0.20);
                border-radius: 10px;
            }
        """)
        lay_prog = QVBoxLayout(self.panel_progreso)
        lay_prog.setContentsMargins(20, 16, 20, 16)
        lay_prog.setSpacing(8)

        self.lbl_progreso_etapa = QLabel("Iniciando…")
        self.lbl_progreso_etapa.setStyleSheet(
            "color: #01696f; font-size: 13px; font-weight: 600;"
        )
        lay_prog.addWidget(self.lbl_progreso_etapa)

        self.barra_progreso = QProgressBar()
        self.barra_progreso.setRange(0, 100)
        self.barra_progreso.setValue(0)
        self.barra_progreso.setFixedHeight(10)
        self.barra_progreso.setTextVisible(False)
        self.barra_progreso.setStyleSheet("""
            QProgressBar {
                background: #e6e4df;
                border: none;
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #01696f, stop:1 #437a22
                );
                border-radius: 5px;
            }
        """)
        lay_prog.addWidget(self.barra_progreso)

        self.panel_progreso.hide()
        lay_cuerpo.addWidget(self.panel_progreso)

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
            QPushButton:hover    { background: #2e5c10; }
            QPushButton:pressed  { background: #1e3f0a; }
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
        self._worker.progreso.connect(self._on_progreso)
        self._worker.listo.connect(self._on_listo)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _set_guardando(self, guardando: bool):
        self.btn_guardar.setEnabled(not guardando)
        self.btn_volver.setEnabled(not guardando)
        self.input_nombre.setEnabled(not guardando)

        if guardando:
            self.btn_guardar.setText("Guardando…")
            self.lbl_estado.setText("Procesando, no cierres la ventana…")
            self.lbl_estado.setStyleSheet(
                "color: #01696f; font-size: 13px; font-weight: 600;"
            )
            # Mostrar barra de progreso
            self.barra_progreso.setValue(0)
            self.lbl_progreso_etapa.setText("Iniciando…")
            self.panel_progreso.show()
        else:
            self.btn_guardar.setText("Guardar documento  ✓")
            self.lbl_estado.setText("Revisá el nombre y confirmá para guardar.")
            self.lbl_estado.setStyleSheet("color: #7a7974; font-size: 13px;")
            self.panel_progreso.hide()

    def _on_progreso(self, porcentaje: int, etiqueta: str):
        self.barra_progreso.setValue(porcentaje)
        self.lbl_progreso_etapa.setText(etiqueta)

    def _on_listo(self, ruta_str: str):
        self._set_guardando(False)
        self.guardado_listo.emit(Path(ruta_str))

    def _on_error(self, mensaje: str):
        self._set_guardando(False)
        QMessageBox.critical(
            self,
            "Error al guardar",
            f"No se pudo guardar el documento:\n\n{mensaje}\n\n"
            "Verificá que pypdf (o PyPDF2) y Pillow estén instalados.",
        )
