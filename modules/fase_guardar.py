# modules/fase_guardar.py
# Fase 4: Confirmación, reemplazo de página, renombrar y guardar.
#
# Recibe:
#   ruta_pdf   (str)  — PDF original abierto en la app
#   num_pagina (int)  — índice 0-based de la página a reemplazar
#   ruta_img   (str)  — imagen escaneada/cargada desde fase3_scan
#
# Señales públicas:
#   guardado_ok(str)  — ruta final del PDF guardado (puede ser nueva)
#   cancelar()        — volver al grid de páginas sin guardar

import os
import shutil
import tempfile

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QSpacerItem, QFileDialog,
    QInputDialog, QMessageBox, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QFont

try:
    import fitz  # PyMuPDF
    PYMUPDF_DISPONIBLE = True
except ImportError:
    PYMUPDF_DISPONIBLE = False


# ─────────────────────────────────────────────────────────────────────────
#  Worker: hace el reemplazo real del PDF en hilo separado
# ─────────────────────────────────────────────────────────────────────────
class ReemplazarPaginaWorker(QThread):
    """
    Abre el PDF original, elimina la página indicada e inserta la imagen
    escaneada como nueva página (mismo tamaño que la original).
    Guarda en ruta_destino.
    """
    terminado = pyqtSignal(str)   # ruta_destino si OK
    error     = pyqtSignal(str)   # mensaje si falla

    def __init__(
        self,
        ruta_pdf: str,
        num_pagina: int,
        ruta_img: str,
        ruta_destino: str,
        parent=None,
    ):
        super().__init__(parent)
        self.ruta_pdf      = ruta_pdf
        self.num_pagina    = num_pagina
        self.ruta_img      = ruta_img
        self.ruta_destino  = ruta_destino

    def run(self):
        try:
            doc = fitz.open(self.ruta_pdf)

            # Guardar dimensiones originales de la página antes de borrarla
            pagina_orig = doc[self.num_pagina]
            w_orig = pagina_orig.rect.width
            h_orig = pagina_orig.rect.height

            # Eliminar la página original
            doc.delete_page(self.num_pagina)

            # Crear página nueva con las mismas dimensiones
            doc.insert_page(
                self.num_pagina,
                width=w_orig,
                height=h_orig,
            )

            # Insertar la imagen ocupando toda la página nueva
            nueva_pag = doc[self.num_pagina]
            rect_pagina = fitz.Rect(0, 0, w_orig, h_orig)
            nueva_pag.insert_image(rect_pagina, filename=self.ruta_img)

            # Guardar en ruta destino (puede ser la misma o una nueva)
            doc.save(self.ruta_destino, garbage=4, deflate=True)
            doc.close()

            self.terminado.emit(self.ruta_destino)

        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────────────────
#  Panel de comparación: Original ↔ Escaneada
# ─────────────────────────────────────────────────────────────────────────
class PanelComparacion(QFrame):
    """Muestra el thumbnail de la página original junto a la imagen escaneada."""

    def __init__(self, ruta_pdf: str, num_pagina: int, ruta_img: str, parent=None):
        super().__init__(parent)
        self.ruta_pdf   = ruta_pdf
        self.num_pagina = num_pagina
        self.ruta_img   = ruta_img

        self.setStyleSheet("""
            PanelComparacion {
                background: #f9f8f5;
                border: 1px solid rgba(40,37,29,0.10);
                border-radius: 10px;
            }
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(32)

        lay.addStretch()
        lay.addWidget(self._bloque_pagina_original())
        lay.addWidget(self._flecha())
        lay.addWidget(self._bloque_imagen_nueva())
        lay.addStretch()

    # ── Bloque izquierdo: página original del PDF ──────────────────────
    def _bloque_pagina_original(self) -> QWidget:
        cont = QWidget()
        cont.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(cont)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        lbl_titulo = QLabel("Página original")
        lbl_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_titulo.setStyleSheet("color: #7a7974; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;")
        lay.addWidget(lbl_titulo)

        lbl_img = QLabel()
        lbl_img.setFixedSize(140, 185)
        lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_img.setStyleSheet("background: #edeae5; border-radius: 6px;")

        # Intentar renderizar thumbnail de la página original
        if PYMUPDF_DISPONIBLE:
            try:
                doc = fitz.open(self.ruta_pdf)
                pag = doc[self.num_pagina]
                zoom = 140 / pag.rect.width
                pix  = pag.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                img  = QImage(
                    bytes(pix.samples), pix.width, pix.height,
                    pix.stride, QImage.Format.Format_RGB888
                )
                pm = QPixmap.fromImage(img)
                lbl_img.setPixmap(
                    pm.scaled(140, 185, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )
                doc.close()
            except Exception:
                lbl_img.setText("—")
        else:
            lbl_img.setText("Sin PyMuPDF")

        lay.addWidget(lbl_img)

        lbl_num = QLabel(f"Página {self.num_pagina + 1}")
        lbl_num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_num.setStyleSheet("color: #28251d; font-size: 12px; font-weight: 500;")
        lay.addWidget(lbl_num)

        return cont

    # ── Flecha central ─────────────────────────────────────────────────
    def _flecha(self) -> QLabel:
        lbl = QLabel("→")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #01696f; font-size: 26px; font-weight: 700; background: transparent;")
        return lbl

    # ── Bloque derecho: imagen escaneada ───────────────────────────────
    def _bloque_imagen_nueva(self) -> QWidget:
        cont = QWidget()
        cont.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(cont)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        lbl_titulo = QLabel("Imagen escaneada")
        lbl_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_titulo.setStyleSheet("color: #01696f; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;")
        lay.addWidget(lbl_titulo)

        lbl_img = QLabel()
        lbl_img.setFixedSize(140, 185)
        lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_img.setStyleSheet("""
            background: #edeae5;
            border-radius: 6px;
            border: 2px solid rgba(1,105,111,0.35);
        """)

        pm = QPixmap(self.ruta_img)
        if not pm.isNull():
            lbl_img.setPixmap(
                pm.scaled(140, 185, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        else:
            lbl_img.setText("Sin preview")

        lay.addWidget(lbl_img)

        nombre = os.path.basename(self.ruta_img)
        lbl_nombre = QLabel(nombre)
        lbl_nombre.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_nombre.setStyleSheet("color: #01696f; font-size: 12px; font-weight: 500;")
        lbl_nombre.setMaximumWidth(180)
        lbl_nombre.setWordWrap(True)
        lay.addWidget(lbl_nombre)

        return cont


# ─────────────────────────────────────────────────────────────────────────
#  Vista principal — Fase 4
# ─────────────────────────────────────────────────────────────────────────
class VistaGuardar(QWidget):
    """
    Señales públicas:
      guardado_ok(str)  → ruta final del PDF guardado
      cancelar()        → volver al grid de páginas
    """
    guardado_ok = pyqtSignal(str)
    cancelar    = pyqtSignal()

    def __init__(
        self,
        ruta_pdf: str,
        num_pagina: int,
        ruta_img: str,
        parent=None,
    ):
        super().__init__(parent)
        self.ruta_pdf    = ruta_pdf
        self.num_pagina  = num_pagina
        self.ruta_img    = ruta_img
        self._worker: ReemplazarPaginaWorker | None = None

        if not PYMUPDF_DISPONIBLE:
            self._mostrar_error_dependencia()
            return

        self._construir_ui()

    # ══════════════════════════════════════════════════════════════════
    #  Construcción de UI
    # ══════════════════════════════════════════════════════════════════
    def _construir_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        raiz.addWidget(self._cabecera())

        # Cuerpo scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { background: #f7f6f2; border: none; }
            QScrollBar:vertical {
                background: #f3f0ec; width: 8px; border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #bab9b4; border-radius: 4px; min-height: 28px;
            }
            QScrollBar::handle:vertical:hover { background: #7a7974; }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
        """)

        cuerpo = QWidget()
        cuerpo.setStyleSheet("background: #f7f6f2;")
        lay_cuerpo = QVBoxLayout(cuerpo)
        lay_cuerpo.setContentsMargins(40, 28, 40, 28)
        lay_cuerpo.setSpacing(20)

        # Descripción
        lbl_desc = QLabel(
            f"La página <b>{self.num_pagina + 1}</b> del PDF será reemplazada "
            "por la imagen que aparece a la derecha. "
            "Revisa la comparación y elige cómo guardar."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #7a7974; font-size: 13px;")
        lay_cuerpo.addWidget(lbl_desc)

        # Panel de comparación Original ↔ Nueva
        lay_cuerpo.addWidget(
            PanelComparacion(self.ruta_pdf, self.num_pagina, self.ruta_img)
        )

        # Panel de opciones de guardado
        lay_cuerpo.addWidget(self._panel_opciones())

        lay_cuerpo.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        scroll.setWidget(cuerpo)
        raiz.addWidget(scroll, 1)
        raiz.addWidget(self._barra_inferior())

    # ── Cabecera ───────────────────────────────────────────────────────
    def _cabecera(self) -> QFrame:
        cab = QFrame()
        cab.setFixedHeight(64)
        cab.setStyleSheet("""
            QFrame {
                background: #f3f0ec;
                border-bottom: 1px solid rgba(40,37,29,0.10);
            }
        """)
        lay = QHBoxLayout(cab)
        lay.setContentsMargins(20, 0, 20, 0)

        nombre = os.path.basename(self.ruta_pdf)
        lbl_titulo = QLabel(
            f"Confirmar y guardar  ·  Página {self.num_pagina + 1}  ·  {nombre}"
        )
        font_cab = QFont("Segoe UI", 13)
        font_cab.setWeight(QFont.Weight.Medium)
        lbl_titulo.setFont(font_cab)
        lbl_titulo.setStyleSheet("color: #28251d;")
        lay.addWidget(lbl_titulo)

        lay.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        btn_volver = QPushButton("← Cambiar imagen")
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
        btn_volver.clicked.connect(self.cancelar)
        lay.addWidget(btn_volver)

        return cab

    # ── Panel de opciones de guardado ──────────────────────────────────
    def _panel_opciones(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background: #f9f8f5;
                border: 1px solid rgba(40,37,29,0.10);
                border-radius: 10px;
            }
        """)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(14)

        font_h = QFont("Segoe UI", 12)
        font_h.setWeight(QFont.Weight.Medium)

        titulo = QLabel("Opciones de guardado")
        titulo.setFont(font_h)
        titulo.setStyleSheet("color: #28251d;")
        lay.addWidget(titulo)

        # Fila: nombre actual del archivo
        fila_nombre = QHBoxLayout()
        fila_nombre.setSpacing(10)

        lbl_icon_doc = QLabel("📄")
        lbl_icon_doc.setFixedWidth(20)
        lbl_icon_doc.setStyleSheet("font-size: 15px; background: transparent;")
        fila_nombre.addWidget(lbl_icon_doc)

        nombre_actual = os.path.basename(self.ruta_pdf)
        self.lbl_nombre_archivo = QLabel(nombre_actual)
        self.lbl_nombre_archivo.setStyleSheet(
            "color: #28251d; font-size: 13px; font-weight: 500; background: transparent;"
        )
        fila_nombre.addWidget(self.lbl_nombre_archivo)
        fila_nombre.addStretch()

        btn_renombrar = QPushButton("Renombrar…")
        btn_renombrar.setFixedHeight(30)
        btn_renombrar.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #01696f;
                border: 1px solid rgba(1,105,111,0.45);
                border-radius: 5px;
                padding: 0 12px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover { background: #01696f; color: white; border-color: #01696f; }
        """)
        btn_renombrar.clicked.connect(self._on_renombrar)
        fila_nombre.addWidget(btn_renombrar)

        lay.addLayout(fila_nombre)

        # Divisor
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet("background: rgba(40,37,29,0.08); border: none;")
        lay.addWidget(div)

        # Descripción opciones
        lbl_opc = QLabel(
            "Elige si reemplazar el archivo original o guardarlo con un nombre distinto:"
        )
        lbl_opc.setWordWrap(True)
        lbl_opc.setStyleSheet("color: #7a7974; font-size: 12px; background: transparent;")
        lay.addWidget(lbl_opc)

        return panel

    # ── Barra inferior ─────────────────────────────────────────────────
    def _barra_inferior(self) -> QFrame:
        barra = QFrame()
        barra.setFixedHeight(68)
        barra.setStyleSheet("""
            QFrame {
                background: #f9f8f5;
                border-top: 1px solid rgba(40,37,29,0.10);
            }
        """)
        lay = QHBoxLayout(barra)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(10)

        self.lbl_estado_inf = QLabel("Listo para guardar.")
        self.lbl_estado_inf.setStyleSheet("color: #7a7974; font-size: 13px;")
        lay.addWidget(self.lbl_estado_inf)

        lay.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        # Botón "Guardar como…"
        self.btn_guardar_como = QPushButton("Guardar como…")
        self.btn_guardar_como.setFixedHeight(40)
        self.btn_guardar_como.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #01696f;
                border: 1px solid rgba(1,105,111,0.55);
                border-radius: 7px;
                padding: 0 20px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover { background: #e4f2f1; border-color: #01696f; }
            QPushButton:pressed { background: #cedcd8; }
            QPushButton:disabled { color: #bab9b4; border-color: rgba(40,37,29,0.15); }
        """)
        self.btn_guardar_como.clicked.connect(self._on_guardar_como)
        lay.addWidget(self.btn_guardar_como)

        # Botón "Reemplazar original"
        self.btn_reemplazar = QPushButton("Reemplazar original  ✓")
        self.btn_reemplazar.setFixedHeight(40)
        self.btn_reemplazar.setStyleSheet("""
            QPushButton {
                background: #01696f;
                color: white;
                border: none;
                border-radius: 7px;
                padding: 0 22px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover   { background: #0c4e54; }
            QPushButton:pressed { background: #0f3638; }
            QPushButton:disabled { background: #dcd9d5; color: #bab9b4; }
        """)
        self.btn_reemplazar.clicked.connect(self._on_reemplazar_original)
        lay.addWidget(self.btn_reemplazar)

        return barra

    # ══════════════════════════════════════════════════════════════════
    #  Lógica de acciones
    # ══════════════════════════════════════════════════════════════════

    # ── Renombrar (solo cambia el nombre que se mostrará al guardar) ───
    def _on_renombrar(self):
        nombre_actual = self.lbl_nombre_archivo.text()
        base, ext = os.path.splitext(nombre_actual)
        nuevo, ok = QInputDialog.getText(
            self,
            "Renombrar archivo",
            "Nuevo nombre del archivo (sin extensión):",
            text=base,
        )
        if ok and nuevo.strip():
            nuevo = nuevo.strip()
            # Asegurar que no tenga caracteres inválidos en nombres de archivo
            for c in r'\/:*?"<>|':
                nuevo = nuevo.replace(c, "_")
            self.lbl_nombre_archivo.setText(nuevo + ext)

    # ── Guardar como… (elige carpeta y nombre) ─────────────────────────
    def _on_guardar_como(self):
        nombre_sugerido = self.lbl_nombre_archivo.text()
        carpeta_orig    = os.path.dirname(self.ruta_pdf)

        ruta_dest, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar PDF como…",
            os.path.join(carpeta_orig, nombre_sugerido),
            "PDF (*.pdf)",
        )
        if ruta_dest:
            if not ruta_dest.lower().endswith(".pdf"):
                ruta_dest += ".pdf"
            self._ejecutar_guardado(ruta_dest)

    # ── Reemplazar original ────────────────────────────────────────────
    def _on_reemplazar_original(self):
        resp = QMessageBox.question(
            self,
            "Confirmar reemplazo",
            f"¿Reemplazar el archivo original?\n\n{self.ruta_pdf}\n\n"
            "Esta acción no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if resp == QMessageBox.StandardButton.Yes:
            # Guardar primero en un temporal y luego mover sobre el original
            tmp = tempfile.mktemp(suffix=".pdf", prefix="pdf_sign_tmp_")
            self._ejecutar_guardado(tmp, ruta_final=self.ruta_pdf)

    # ── Ejecuta el Worker de reemplazo ─────────────────────────────────
    def _ejecutar_guardado(self, ruta_destino: str, ruta_final: str | None = None):
        self._bloquear_botones(True)
        self.lbl_estado_inf.setText("Procesando PDF…")
        self.lbl_estado_inf.setStyleSheet("color: #7a7974; font-size: 13px;")

        self._ruta_final_override = ruta_final  # None = la destino ya es la final

        self._worker = ReemplazarPaginaWorker(
            ruta_pdf=self.ruta_pdf,
            num_pagina=self.num_pagina,
            ruta_img=self.ruta_img,
            ruta_destino=ruta_destino,
        )
        self._worker.terminado.connect(self._on_worker_ok)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_worker_ok(self, ruta_tmp: str):
        self._bloquear_botones(False)

        # Si hay un "ruta_final_override" significa que guardamos en temporal
        # y hay que moverlo sobre el original
        ruta_final = self._ruta_final_override
        if ruta_final:
            try:
                shutil.move(ruta_tmp, ruta_final)
            except Exception as e:
                self._on_worker_error(f"No se pudo reemplazar el original:\n{e}")
                return
        else:
            ruta_final = ruta_tmp

        self.lbl_estado_inf.setText("¡Guardado correctamente!")
        self.lbl_estado_inf.setStyleSheet(
            "color: #437a22; font-size: 13px; font-weight: 600;"
        )
        self.guardado_ok.emit(ruta_final)

    def _on_worker_error(self, msg: str):
        self._bloquear_botones(False)
        self.lbl_estado_inf.setText("Error al guardar.")
        self.lbl_estado_inf.setStyleSheet("color: #a12c7b; font-size: 13px;")
        QMessageBox.critical(
            self,
            "Error al guardar",
            f"No se pudo guardar el PDF:\n\n{msg}",
        )

    def _bloquear_botones(self, bloquear: bool):
        self.btn_reemplazar.setEnabled(not bloquear)
        self.btn_guardar_como.setEnabled(not bloquear)

    # ══════════════════════════════════════════════════════════════════
    #  Error de dependencia
    # ══════════════════════════════════════════════════════════════════
    def _mostrar_error_dependencia(self):
        lay = QVBoxLayout(self)
        lbl = QLabel(
            "⚠  PyMuPDF no está instalado.\n"
            "Ejecuta en terminal:  pip install pymupdf"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "color: #a13544; font-size: 14px; padding: 60px 40px;"
        )
        lay.addWidget(lbl)

    # ══════════════════════════════════════════════════════════════════
    #  Limpieza al cerrar
    # ══════════════════════════════════════════════════════════════════
    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.wait()
        super().closeEvent(event)
