# modules/fase1_preview.py
# Fase 1: Vista de páginas del PDF para selección
# Muestra todas las páginas como thumbnails clicables en un grid scrollable.

import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QGridLayout, QFrame,
    QSizePolicy, QSpacerItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QFont, QColor, QPainter, QBrush

try:
    import fitz  # PyMuPDF
    PYMUPDF_DISPONIBLE = True
except ImportError:
    PYMUPDF_DISPONIBLE = False


# ─────────────────────────────────────────────────────────────
#  Worker: renderiza thumbnails en hilo separado (no bloquea UI)
# ─────────────────────────────────────────────────────────────
class RenderWorker(QThread):
    thumbnail_listo = pyqtSignal(int, QPixmap)   # (num_pagina 0-based, pixmap)
    terminado       = pyqtSignal(int)            # total de páginas renderizadas

    def __init__(self, ruta_pdf: str, thumb_w: int = 190):
        super().__init__()
        self.ruta_pdf = ruta_pdf
        self.thumb_w  = thumb_w
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True

    def run(self):
        if not PYMUPDF_DISPONIBLE:
            self.terminado.emit(0)
            return
        try:
            doc   = fitz.open(self.ruta_pdf)
            total = len(doc)
            for i, pagina in enumerate(doc):
                if self._cancelado:
                    break
                zoom = self.thumb_w / pagina.rect.width
                mat  = fitz.Matrix(zoom, zoom)
                pix  = pagina.get_pixmap(matrix=mat, alpha=False)
                img  = QImage(
                    pix.samples, pix.width, pix.height,
                    pix.stride, QImage.Format.Format_RGB888
                )
                self.thumbnail_listo.emit(i, QPixmap.fromImage(img))
            doc.close()
            self.terminado.emit(total)
        except Exception as e:
            print(f"[RenderWorker] Error: {e}")
            self.terminado.emit(0)


# ─────────────────────────────────────────────────────────────
#  Tarjeta individual de página
# ─────────────────────────────────────────────────────────────
class TarjetaPagina(QFrame):
    seleccionada = pyqtSignal(int)   # emite el número de página (0-based)

    _ESTILO_NORMAL = """
        TarjetaPagina {
            background: #f9f8f5;
            border: 2px solid rgba(40,37,29,0.10);
            border-radius: 8px;
        }
        TarjetaPagina:hover {
            border: 2px solid #01696f;
            background: #f0f7f7;
        }
    """
    _ESTILO_ACTIVA = """
        TarjetaPagina {
            background: #cedcd8;
            border: 2px solid #01696f;
            border-radius: 8px;
        }
    """

    def __init__(self, num_pagina: int, parent=None):
        super().__init__(parent)
        self.num_pagina = num_pagina
        self.setFixedWidth(174)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._ESTILO_NORMAL)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(7, 7, 7, 7)
        lay.setSpacing(6)

        # Imagen / thumbnail
        self.lbl_img = QLabel()
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_img.setFixedHeight(230)
        self.lbl_img.setStyleSheet("background: #edeae5; border-radius: 4px;")
        self._mostrar_skeleton()
        lay.addWidget(self.lbl_img)

        # Etiqueta de número
        self.lbl_num = QLabel(f"Página {num_pagina + 1}")
        self.lbl_num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont("Segoe UI", 11)
        f.setWeight(QFont.Weight.Medium)
        self.lbl_num.setFont(f)
        self.lbl_num.setStyleSheet("color: #28251d; padding: 2px 0 3px;")
        lay.addWidget(self.lbl_num)

    # ── Skeleton mientras carga ────────────────
    def _mostrar_skeleton(self):
        ph = QPixmap(160, 214)
        ph.fill(QColor("#dcd9d5"))
        p = QPainter(ph)
        p.setBrush(QBrush(QColor("#c4c1bb")))
        p.setPen(Qt.PenStyle.NoPen)
        for y in [50, 72, 94, 116, 138, 160, 182]:
            w = 110 if y % 44 == 0 else 80
            p.drawRoundedRect(25, y, w, 7, 3, 3)
        p.end()
        self.lbl_img.setPixmap(ph)

    # ── Recibe thumbnail real ──────────────────
    def set_pixmap(self, pixmap: QPixmap):
        scaled = pixmap.scaledToWidth(160, Qt.TransformationMode.SmoothTransformation)
        self.lbl_img.setPixmap(scaled)
        self.lbl_img.setFixedHeight(scaled.height())

    # ── Estado visual seleccionado/normal ──────
    def marcar(self, activa: bool):
        self.setStyleSheet(self._ESTILO_ACTIVA if activa else self._ESTILO_NORMAL)
        color = "#01696f" if activa else "#28251d"
        peso  = "bold"    if activa else "500"
        self.lbl_num.setStyleSheet(
            f"color:{color}; font-weight:{peso}; padding:2px 0 3px;"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.seleccionada.emit(self.num_pagina)
        super().mousePressEvent(event)


# ─────────────────────────────────────────────────────────────
#  Vista principal — Fase 1
# ─────────────────────────────────────────────────────────────
class VistaPrevisualizacion(QWidget):
    """
    Señales públicas:
      pagina_seleccionada(int)  →  número de página elegida (0-based)
      cancelar()                →  usuario sale sin seleccionar
    """
    pagina_seleccionada = pyqtSignal(int)
    cancelar            = pyqtSignal()

    COLS_POR_DEFECTO = 4   # columnas iniciales; se recalcula al resize

    def __init__(self, ruta_pdf: str, parent=None):
        super().__init__(parent)
        self.ruta_pdf       = ruta_pdf
        self.tarjetas: list[TarjetaPagina] = []
        self._pagina_activa: int | None    = None
        self._worker: RenderWorker | None  = None
        self._total_paginas = 0

        self._construir_ui()
        self._iniciar_render()

    # ══════════════════════════════════════════
    #  Construcción de la UI
    # ══════════════════════════════════════════
    def _construir_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        self.setStyleSheet("background: #f7f6f2;")

        # ── Cabecera ────────────────────────────────────────
        cab = QFrame()
        cab.setFixedHeight(60)
        cab.setStyleSheet("""
            QFrame {
                background: #f3f0ec;
                border-bottom: 1px solid rgba(40,37,29,0.09);
            }
        """)
        lay_cab = QHBoxLayout(cab)
        lay_cab.setContentsMargins(20, 0, 20, 0)

        nombre = os.path.basename(self.ruta_pdf)
        lbl_titulo = QLabel(f"Selecciona una página  ·  {nombre}")
        ft = QFont("Segoe UI", 13)
        ft.setWeight(QFont.Weight.Medium)
        lbl_titulo.setFont(ft)
        lbl_titulo.setStyleSheet("color: #28251d;")
        lay_cab.addWidget(lbl_titulo)

        lay_cab.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        self.lbl_conteo = QLabel("Cargando…")
        self.lbl_conteo.setStyleSheet("color: #7a7974; font-size: 12px;")
        lay_cab.addWidget(self.lbl_conteo)

        lay_cab.addSpacing(16)

        btn_cancelar = QPushButton("✕  Cancelar")
        btn_cancelar.setFixedHeight(34)
        btn_cancelar.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #a13544;
                border: 1px solid rgba(161,53,68,0.4);
                border-radius: 6px;
                padding: 0 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover   { background: #a13544; color: white; border-color: #a13544; }
            QPushButton:pressed { background: #782b33; }
        """)
        btn_cancelar.clicked.connect(self._on_cancelar)
        lay_cab.addWidget(btn_cancelar)
        raiz.addWidget(cab)

        # ── Área scrollable con grid ─────────────────────────
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("""
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

        self._cont_grid = QWidget()
        self._cont_grid.setStyleSheet("background: #f7f6f2;")
        self.grid = QGridLayout(self._cont_grid)
        self.grid.setContentsMargins(24, 24, 24, 32)
        self.grid.setSpacing(14)
        self.scroll.setWidget(self._cont_grid)
        raiz.addWidget(self.scroll, 1)

        # ── Barra inferior ───────────────────────────────────
        inf = QFrame()
        inf.setFixedHeight(60)
        inf.setStyleSheet("""
            QFrame {
                background: #f9f8f5;
                border-top: 1px solid rgba(40,37,29,0.09);
            }
        """)
        lay_inf = QHBoxLayout(inf)
        lay_inf.setContentsMargins(20, 0, 20, 0)

        self.lbl_estado = QLabel("Haz clic en una página para seleccionarla")
        self.lbl_estado.setStyleSheet("color: #7a7974; font-size: 13px;")
        lay_inf.addWidget(self.lbl_estado)

        lay_inf.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        self.btn_continuar = QPushButton("Imprimir página seleccionada  →")
        self.btn_continuar.setFixedHeight(38)
        self.btn_continuar.setEnabled(False)
        self.btn_continuar.setStyleSheet("""
            QPushButton {
                background: #01696f;
                color: white;
                border: none;
                border-radius: 7px;
                padding: 0 20px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover    { background: #0c4e54; }
            QPushButton:pressed  { background: #0f3638; }
            QPushButton:disabled { background: #dcd9d5; color: #bab9b4; }
        """)
        self.btn_continuar.clicked.connect(self._on_continuar)
        lay_inf.addWidget(self.btn_continuar)
        raiz.addWidget(inf)

    # ══════════════════════════════════════════
    #  Render de thumbnails
    # ══════════════════════════════════════════
    def _iniciar_render(self):
        if not PYMUPDF_DISPONIBLE:
            self._error_dependencia()
            return
        self._worker = RenderWorker(self.ruta_pdf)
        self._worker.thumbnail_listo.connect(self._agregar_thumbnail)
        self._worker.terminado.connect(self._render_terminado)
        self._worker.start()

    def _agregar_thumbnail(self, num: int, pixmap: QPixmap):
        # Calcular columnas según ancho real del viewport
        vp_w = self.scroll.viewport().width()
        cols = max(2, (max(vp_w, 500) - 48) // (174 + 14))

        tarjeta = TarjetaPagina(num)
        tarjeta.set_pixmap(pixmap)
        tarjeta.seleccionada.connect(self._on_tarjeta_click)

        self.grid.addWidget(tarjeta, num // cols, num % cols)
        self.tarjetas.append(tarjeta)

    def _render_terminado(self, total: int):
        self._total_paginas = total
        if total > 0:
            s = "s" if total != 1 else ""
            self.lbl_conteo.setText(f"{total} página{s}")
        else:
            self.lbl_conteo.setText("Sin páginas")

    # ══════════════════════════════════════════
    #  Interacción
    # ══════════════════════════════════════════
    def _on_tarjeta_click(self, num: int):
        # Deseleccionar la anterior
        if self._pagina_activa is not None:
            idx = self._pagina_activa
            if 0 <= idx < len(self.tarjetas):
                self.tarjetas[idx].marcar(False)

        self._pagina_activa = num
        self.tarjetas[num].marcar(True)

        self.lbl_estado.setText(
            f"✔  Página {num + 1} seleccionada  ·  Lista para imprimir"
        )
        self.lbl_estado.setStyleSheet(
            "color: #01696f; font-size: 13px; font-weight: 600;"
        )
        self.btn_continuar.setEnabled(True)

    def _on_continuar(self):
        if self._pagina_activa is not None:
            self.pagina_seleccionada.emit(self._pagina_activa)

    def _on_cancelar(self):
        self._detener_worker()
        self.cancelar.emit()

    # ══════════════════════════════════════════
    #  Utilidades
    # ══════════════════════════════════════════
    def _detener_worker(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancelar()
            self._worker.wait()

    def _error_dependencia(self):
        lbl = QLabel(
            "⚠  PyMuPDF no está instalado.\n"
            "Ejecuta en terminal:  pip install pymupdf"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "color: #a13544; font-size: 14px; padding: 60px 40px;"
        )
        self.layout().insertWidget(1, lbl)

    def closeEvent(self, event):
        self._detener_worker()
        super().closeEvent(event)