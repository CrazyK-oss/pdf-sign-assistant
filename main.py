"""
PDF Sign Assistant — main.py
============================================================
Flujo principal:
  1. Pantalla de inicio: botón "Abrir PDF" + lista de trabajos ya guardados.
     — NO hay lista de PDFs al inicio, solo el botón para abrir uno.
  2. Cuando hay un PDF en trabajo: panel activo siempre visible con botón
     Cancelar prominente. El botón "Abrir PDF" se deshabilita.
  3. El panel activo delega a:
       fase1_preview → fase2_print → fase3_scan → fase_guardar
  4. Al confirmar se añade a la lista de guardados (con fecha/hora).
  5. Doble‑clic en guardado → vuelve a abrir ese PDF para re‑editar.
  6. Seleccionar guardado → habilita botones Editar y Enviar correo.
"""

import sys
import os
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from modules.fase1_preview import VistaPrevisualizacion


# ── Bootstrap: instala dependencias si faltan ────────────────────────────────
def _instalar_deps():
    reqs = Path(__file__).parent / "requirements.txt"
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", str(reqs),
         "--no-warn-script-location", "--quiet"]
    )


try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
        QMessageBox, QFrame, QSizePolicy, QStatusBar, QAbstractItemView,
        QSpacerItem,
    )
    from PyQt6.QtCore import Qt, QSize
    from PyQt6.QtGui import QFont, QColor
except ImportError:
    _instalar_deps()
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
        QMessageBox, QFrame, QSizePolicy, QStatusBar, QAbstractItemView,
        QSpacerItem,
    )
    from PyQt6.QtCore import Qt, QSize
    from PyQt6.QtGui import QFont, QColor


load_dotenv(Path(__file__).parent / ".env")

BASE_DIR        = Path(__file__).parent
CARPETA_TRABAJO = BASE_DIR / "pdfs_trabajo"
CARPETA_FIRMADO = BASE_DIR / "pdfs_firmados"
CONFIG_PATH     = BASE_DIR / "config.json"
CARPETA_TRABAJO.mkdir(exist_ok=True)
CARPETA_FIRMADO.mkdir(exist_ok=True)


# ── Paleta de colores ─────────────────────────────────────────────────────────
C_BG           = "#f7f6f2"
C_SURFACE      = "#f3f0ec"
C_SURFACE_2    = "#edeae5"
C_BORDER       = "#d4d1ca"
C_BORDER_SOFT  = "#e0ddd7"
C_TEXT         = "#28251d"
C_MUTED        = "#7a7974"
C_FAINT        = "#bab9b4"
C_PRIMARY      = "#01696f"
C_PRIMARY_H    = "#0c4e54"
C_PRIMARY_A    = "#0f3638"
C_PRIMARY_HL   = "#cedcd8"
C_DANGER       = "#a13544"
C_DANGER_H     = "#782b33"
C_SUCCESS      = "#437a22"
C_SUCCESS_H    = "#2e5c10"
C_SUCCESS_BG   = "#d4dfcc"
C_ACTIVE_BG    = "#e4f0ee"
C_ACTIVE_BD    = "#01696f"


STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {C_BG};
    color: {C_TEXT};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}

/* ── Botón primario ── */
QPushButton {{
    background-color: {C_PRIMARY};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton:hover   {{ background-color: {C_PRIMARY_H}; }}
QPushButton:pressed {{ background-color: {C_PRIMARY_A}; }}
QPushButton:disabled {{
    background-color: {C_BORDER};
    color: {C_MUTED};
}}

/* ── Botón peligro ── */
QPushButton[danger="true"] {{
    background-color: {C_DANGER};
    color: white;
}}
QPushButton[danger="true"]:hover   {{ background-color: {C_DANGER_H}; }}
QPushButton[danger="true"]:pressed {{ background-color: #521f24; }}

/* ── Botón secundario (ghost) ── */
QPushButton[secondary="true"] {{
    background-color: transparent;
    color: {C_PRIMARY};
    border: 1.5px solid {C_PRIMARY};
}}
QPushButton[secondary="true"]:hover {{
    background-color: {C_PRIMARY};
    color: white;
}}
QPushButton[secondary="true"]:disabled {{
    background-color: transparent;
    color: {C_FAINT};
    border-color: {C_BORDER_SOFT};
}}

/* ── Lista de guardados ── */
QListWidget {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    border-radius: 6px;
    padding: 10px 12px;
    margin: 2px 0;
    color: {C_TEXT};
}}
QListWidget::item:hover {{
    background-color: {C_SURFACE_2};
}}
QListWidget::item:selected {{
    background-color: {C_PRIMARY_HL};
    color: {C_TEXT};
}}

/* ── Panel de trabajo activo ── */
QFrame#panelActivo {{
    background-color: {C_ACTIVE_BG};
    border: 1.5px solid {C_ACTIVE_BD};
    border-radius: 10px;
}}

/* ── Panel vacío (sin guardados) ── */
QFrame#panelVacio {{
    background-color: {C_SURFACE};
    border: 1px dashed {C_BORDER};
    border-radius: 10px;
}}

/* ── Etiqueta de sección ── */
QLabel#seccion {{
    font-size: 11px;
    font-weight: 700;
    color: {C_MUTED};
    letter-spacing: 1px;
}}

/* ── Nombre del PDF activo ── */
QLabel#nombreActivo {{
    font-size: 15px;
    font-weight: 600;
    color: {C_TEXT};
}}

/* ── Subtítulo de fecha ── */
QLabel#fechaItem {{
    font-size: 11px;
    color: {C_MUTED};
}}

/* ── Status bar ── */
QStatusBar {{
    background-color: {C_SURFACE};
    border-top: 1px solid {C_BORDER};
    font-size: 12px;
    color: {C_MUTED};
    padding: 2px 8px;
}}

/* ── Separadores ── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {C_BORDER};
    max-height: 1px;
}}
"""


# ── Utilidades ────────────────────────────────────────────────────────────────

def _cargar_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _btn(texto: str, *, danger=False, secondary=False,
         min_w=0, height=36) -> QPushButton:
    b = QPushButton(texto)
    b.setMinimumHeight(height)
    if min_w:
        b.setMinimumWidth(min_w)
    if danger:
        b.setProperty("danger", "true")
        b.style().unpolish(b)
        b.style().polish(b)
    if secondary:
        b.setProperty("secondary", "true")
        b.style().unpolish(b)
        b.style().polish(b)
    return b


def _sep() -> QFrame:
    """Separador horizontal fino."""
    s = QFrame()
    s.setFrameShape(QFrame.Shape.HLine)
    s.setFrameShadow(QFrame.Shadow.Plain)
    return s


# ── Panel PDF activo ──────────────────────────────────────────────────────────

class PanelActivo(QFrame):
    """
    Panel siempre visible cuando hay un PDF en proceso.
    Muestra: nombre del archivo · ruta · botón 'Trabajar páginas' · botón 'Cancelar'.
    """

    def __init__(self, ruta: Path, on_trabajar, on_cancelar, parent=None):
        super().__init__(parent)
        self.setObjectName("panelActivo")
        self.ruta = ruta

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        fila_info = QHBoxLayout()
        fila_info.setSpacing(12)

        icono = QLabel("📄")
        icono.setFont(QFont("Segoe UI Emoji", 22))
        icono.setFixedWidth(36)
        icono.setAlignment(Qt.AlignmentFlag.AlignTop)
        fila_info.addWidget(icono)

        col_info = QVBoxLayout()
        col_info.setSpacing(2)

        lbl_tag = QLabel("PDF EN TRABAJO")
        lbl_tag.setObjectName("seccion")
        col_info.addWidget(lbl_tag)

        lbl_nombre = QLabel(ruta.name)
        lbl_nombre.setObjectName("nombreActivo")
        lbl_nombre.setWordWrap(True)
        col_info.addWidget(lbl_nombre)

        lbl_ruta = QLabel(str(ruta.parent))
        lbl_ruta.setObjectName("fechaItem")
        lbl_ruta.setWordWrap(True)
        col_info.addWidget(lbl_ruta)

        fila_info.addLayout(col_info)
        fila_info.addStretch()
        lay.addLayout(fila_info)

        lay.addWidget(_sep())

        fila_btns = QHBoxLayout()
        fila_btns.setSpacing(8)

        btn_trabajar = _btn("Trabajar páginas →", min_w=200, height=40)
        btn_trabajar.clicked.connect(on_trabajar)
        fila_btns.addWidget(btn_trabajar)

        fila_btns.addStretch()

        btn_cancelar = _btn("✕  Cancelar / Salir del PDF", danger=True, height=40)
        btn_cancelar.clicked.connect(on_cancelar)
        fila_btns.addWidget(btn_cancelar)

        lay.addLayout(fila_btns)


# ── Item de guardados ─────────────────────────────────────────────────────────

class ItemGuardado(QListWidgetItem):
    """Item enriquecido para la lista de PDFs ya modificados."""

    def __init__(self, ruta: Path):
        super().__init__()
        self.ruta = ruta

        try:
            ts = ruta.stat().st_mtime
            fecha = datetime.fromtimestamp(ts).strftime("%d/%m/%Y  %H:%M")
        except Exception:
            fecha = ""

        self.setText(f"{ruta.name}\n{fecha}")
        self.setSizeHint(QSize(0, 58))
        self.setToolTip(str(ruta))


# ── Ventana principal ─────────────────────────────────────────────────────────

class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Sign Assistant")
        self.setMinimumSize(700, 580)
        self.config = _cargar_config()
        self._pdf_activo: Path | None = None
        self._pagina_activa: int = 0
        self._vista_preview   = None
        self._vista_escaneo   = None
        self._vista_guardar   = None
        self._build_ui()
        self._cargar_guardados_existentes()

    # ── Construcción de UI ────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(STYLESHEET)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(0)

        # Header
        header = QHBoxLayout()
        header.setSpacing(12)

        lbl_titulo = QLabel("PDF Sign Assistant")
        lbl_titulo.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        header.addWidget(lbl_titulo)
        header.addStretch()

        self.btn_abrir = _btn("＋  Abrir PDF", min_w=140, height=40)
        self.btn_abrir.clicked.connect(self.abrir_pdf)
        header.addWidget(self.btn_abrir)

        root.addLayout(header)
        root.addSpacing(14)
        root.addWidget(_sep())
        root.addSpacing(14)

        # Panel activo (oculto al inicio)
        self.panel_activo_container = QWidget()
        self.panel_activo_container.setVisible(False)
        self._lay_panel = QVBoxLayout(self.panel_activo_container)
        self._lay_panel.setContentsMargins(0, 0, 0, 0)
        self._lay_panel.setSpacing(0)
        root.addWidget(self.panel_activo_container)

        self._sep_panel = _sep()
        self._sep_panel.setVisible(False)
        root.addWidget(self._sep_panel)

        # Sección: trabajos guardados
        root.addSpacing(14)

        hdr_guardados = QHBoxLayout()
        lbl_guardados = QLabel("TRABAJOS GUARDADOS")
        lbl_guardados.setObjectName("seccion")
        hdr_guardados.addWidget(lbl_guardados)
        hdr_guardados.addStretch()
        self.lbl_contador = QLabel("")
        self.lbl_contador.setObjectName("fechaItem")
        hdr_guardados.addWidget(self.lbl_contador)
        root.addLayout(hdr_guardados)
        root.addSpacing(8)

        # Lista de guardados
        self.lista_guardados = QListWidget()
        self.lista_guardados.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.lista_guardados.setAlternatingRowColors(False)
        self.lista_guardados.itemDoubleClicked.connect(self._reabrir_guardado)
        self.lista_guardados.itemSelectionChanged.connect(self._on_seleccion_guardado)
        self.lista_guardados.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self.lista_guardados)

        # Panel vacío
        self.panel_vacio = QFrame()
        self.panel_vacio.setObjectName("panelVacio")
        lay_vacio = QVBoxLayout(self.panel_vacio)
        lay_vacio.setContentsMargins(24, 32, 24, 32)
        lay_vacio.setSpacing(8)

        icono_vacio = QLabel("📋")
        icono_vacio.setFont(QFont("Segoe UI Emoji", 28))
        icono_vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay_vacio.addWidget(icono_vacio)

        lbl_vacio_titulo = QLabel("Sin documentos modificados todavía")
        lbl_vacio_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_vacio_titulo.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {C_TEXT};"
        )
        lay_vacio.addWidget(lbl_vacio_titulo)

        lbl_vacio_sub = QLabel(
            "Abrí un PDF con el botón de arriba para comenzar a trabajarlo.\n"
            "Los documentos que guardes aparecerán aquí."
        )
        lbl_vacio_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_vacio_sub.setStyleSheet(f"color: {C_MUTED}; font-size: 12px;")
        lbl_vacio_sub.setWordWrap(True)
        lay_vacio.addWidget(lbl_vacio_sub)

        root.addWidget(self.panel_vacio)

        # Barra de acciones sobre guardados
        root.addSpacing(10)
        fila_acciones = QHBoxLayout()
        fila_acciones.setSpacing(8)

        self.btn_reabrir = _btn("✏️  Editar seleccionado",
                                secondary=True, height=36)
        self.btn_reabrir.clicked.connect(self._reabrir_desde_boton)
        self.btn_reabrir.setEnabled(False)
        fila_acciones.addWidget(self.btn_reabrir)

        self.btn_email = _btn("✉️  Enviar por correo",
                              secondary=True, height=36)
        self.btn_email.clicked.connect(self._enviar_correo)
        self.btn_email.setEnabled(False)
        fila_acciones.addWidget(self.btn_email)

        fila_acciones.addStretch()
        root.addLayout(fila_acciones)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Listo — abrí un PDF para comenzar.")

    # ── Estado vacío / lista ──────────────────────────────────────────────

    def _actualizar_estado_vacio(self):
        count = self.lista_guardados.count()
        tiene = count > 0
        self.lista_guardados.setVisible(tiene)
        self.panel_vacio.setVisible(not tiene)
        if tiene:
            self.lbl_contador.setText(
                f"{count} documento{'s' if count > 1 else ''}"
            )
        else:
            self.lbl_contador.setText("")

    def _cargar_guardados_existentes(self):
        """Precarga PDFs de pdfs_firmados/ al iniciar la app."""
        for pdf in sorted(CARPETA_FIRMADO.glob("*.pdf"),
                          key=lambda p: p.stat().st_mtime, reverse=True):
            self._agregar_item_guardado(pdf, scroll=False)
        self._actualizar_estado_vacio()

    def _agregar_item_guardado(self, ruta: Path, scroll=True):
        item = ItemGuardado(ruta)
        self.lista_guardados.insertItem(0, item)
        if scroll:
            self.lista_guardados.scrollToItem(item)
        self._actualizar_estado_vacio()

    # ── Selección de guardados ────────────────────────────────────────────

    def _on_seleccion_guardado(self):
        tiene = bool(self.lista_guardados.selectedItems())
        self.btn_reabrir.setEnabled(tiene)
        self.btn_email.setEnabled(tiene)

    def _item_seleccionado(self) -> "ItemGuardado | None":
        items = self.lista_guardados.selectedItems()
        return items[0] if items else None

    # ── Abrir PDF ─────────────────────────────────────────────────────────

    def abrir_pdf(self):
        """Abre un PDF nuevo. Solo permite uno a la vez."""
        if self._pdf_activo is not None:
            QMessageBox.information(
                self, "PDF en proceso",
                f"Ya hay un PDF en trabajo:\n{self._pdf_activo.name}\n\n"
                "Cancelá o finalizá el trabajo actual antes de abrir otro."
            )
            return

        ruta_str, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar PDF",
            str(Path.home()), "Archivos PDF (*.pdf)"
        )
        if not ruta_str:
            return

        origen  = Path(ruta_str)
        destino = CARPETA_TRABAJO / origen.name
        if destino.exists():
            stem = origen.stem
            ts   = datetime.now().strftime("%H%M%S")
            destino = CARPETA_TRABAJO / f"{stem}_{ts}{origen.suffix}"

        try:
            shutil.copy2(origen, destino)
        except Exception as e:
            QMessageBox.critical(self, "Error al copiar", str(e))
            return

        self._activar_pdf(destino)
        self.status.showMessage(f"PDF cargado: {destino.name}")

    def _activar_pdf(self, ruta: Path):
        """Muestra el panel activo con el PDF cargado."""
        self._pdf_activo = ruta

        while self._lay_panel.count():
            w = self._lay_panel.takeAt(0).widget()
            if w:
                w.deleteLater()

        panel = PanelActivo(
            ruta,
            on_trabajar=self._iniciar_flujo_trabajo,
            on_cancelar=self._cancelar_trabajo,
        )
        self._lay_panel.addWidget(panel)
        self.panel_activo_container.setVisible(True)
        self._sep_panel.setVisible(True)
        self.btn_abrir.setEnabled(False)

    # ── Cancelar trabajo ─────────────────────────────────────────────────

    def _cancelar_trabajo(self):
        if self._pdf_activo is None:
            return
        resp = QMessageBox.question(
            self, "Cancelar trabajo",
            f"¿Seguro que querés salir de:\n{self._pdf_activo.name}?\n\n"
            "Los cambios no guardados se perderán.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        try:
            if self._pdf_activo.exists():
                self._pdf_activo.unlink()
        except Exception:
            pass

        self._cerrar_vistas_abiertas()
        self._desactivar_panel()
        self.status.showMessage("Trabajo cancelado.")

    def _desactivar_panel(self):
        """Oculta el panel activo y libera el estado del PDF."""
        self._pdf_activo = None
        self._pagina_activa = 0
        while self._lay_panel.count():
            w = self._lay_panel.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.panel_activo_container.setVisible(False)
        self._sep_panel.setVisible(False)
        self.btn_abrir.setEnabled(True)

    def _cerrar_vistas_abiertas(self):
        """Cierra y destruye cualquier ventana de fase que esté abierta."""
        for attr in ("_vista_preview", "_vista_escaneo", "_vista_guardar"):
            vista = getattr(self, attr, None)
            if vista is not None:
                vista.close()
                vista.deleteLater()
                setattr(self, attr, None)

    # ── Flujo de trabajo principal ────────────────────────────────────────
    #
    #   fase1_preview  →  _on_pagina_elegida
    #   fase2_print    →  _abrir_escaneo
    #   fase3_scan     →  _on_imagen_escaneada
    #   fase_guardar   →  _on_guardado_listo
    #

    def _iniciar_flujo_trabajo(self):
        """Fase 1 — abre el grid de páginas."""
        if self._pdf_activo is None:
            return

        if self._vista_preview is not None:
            self._vista_preview.close()
            self._vista_preview.deleteLater()
            self._vista_preview = None

        self._vista_preview = VistaPrevisualizacion(str(self._pdf_activo))
        self._vista_preview.setWindowTitle("PDF Sign Assistant — Seleccionar página")
        self._vista_preview.resize(960, 680)
        self._vista_preview.pagina_seleccionada.connect(self._on_pagina_elegida)
        self._vista_preview.cancelar.connect(self._on_preview_cancelado)
        self._vista_preview.show()

    def _on_pagina_elegida(self, num_pagina: int):
        """Fase 2 — impresión directa."""
        self._pagina_activa = num_pagina

        if self._vista_preview is not None:
            self._vista_preview.close()
            self._vista_preview.deleteLater()
            self._vista_preview = None

        from modules.fase2_print import ImpresionPagina
        imprimio = ImpresionPagina.imprimir(
            str(self._pdf_activo), num_pagina, parent=self
        )

        if not imprimio:
            self.status.showMessage("Impresión cancelada — podés elegir otra página.")
            self._iniciar_flujo_trabajo()
            return

        self.status.showMessage(
            f"Página {num_pagina + 1} enviada a la impresora. Esperando escaneo…"
        )
        self._abrir_escaneo(num_pagina)

    def _abrir_escaneo(self, num_pagina: int):
        """Fase 3 — vista de escaneo/carga de imagen."""
        if self._vista_escaneo is not None:
            self._vista_escaneo.close()
            self._vista_escaneo.deleteLater()
            self._vista_escaneo = None

        from modules.fase3_scan import VistaEscaneo
        self._vista_escaneo = VistaEscaneo(
            str(self._pdf_activo), num_pagina, parent=self
        )
        self._vista_escaneo.setWindowTitle("PDF Sign Assistant — Escanear página")
        self._vista_escaneo.resize(820, 560)
        self._vista_escaneo.imagen_lista.connect(self._on_imagen_escaneada)
        self._vista_escaneo.cancelar.connect(self._on_escaneo_cancelado)
        self._vista_escaneo.show()

    def _on_imagen_escaneada(self, ruta_imagen: str):
        """Fase 4 — abre FaseGuardar con la imagen recibida."""
        if self._vista_escaneo is not None:
            self._vista_escaneo.close()
            self._vista_escaneo.deleteLater()
            self._vista_escaneo = None

        self.status.showMessage(
            f"Imagen lista — abriendo confirmación de guardado…"
        )
        self._abrir_guardar(ruta_imagen)

    def _abrir_guardar(self, ruta_imagen: str):
        """Fase 4 — vista de confirmación y guardado del PDF."""
        if self._vista_guardar is not None:
            self._vista_guardar.close()
            self._vista_guardar.deleteLater()
            self._vista_guardar = None

        from modules.fase_guardar import FaseGuardar
        self._vista_guardar = FaseGuardar(
            ruta_pdf        = self._pdf_activo,
            ruta_imagen     = ruta_imagen,
            num_pagina      = self._pagina_activa,
            carpeta_firmados= CARPETA_FIRMADO,
            parent          = self,
        )
        self._vista_guardar.setWindowTitle("PDF Sign Assistant — Guardar documento")
        self._vista_guardar.resize(780, 520)
        self._vista_guardar.guardado_listo.connect(self._on_guardado_listo)
        self._vista_guardar.cancelado.connect(self._on_guardar_cancelado)
        self._vista_guardar.show()

    def _on_guardado_listo(self, ruta_final):
        """El PDF fue guardado correctamente."""
        if self._vista_guardar is not None:
            self._vista_guardar.close()
            self._vista_guardar.deleteLater()
            self._vista_guardar = None

        # Limpiar el PDF de trabajo
        try:
            if self._pdf_activo and self._pdf_activo.exists():
                self._pdf_activo.unlink()
        except Exception:
            pass

        nombre = Path(ruta_final).name
        self._desactivar_panel()
        self._agregar_item_guardado(Path(ruta_final))
        self.status.showMessage(f"✅  Guardado: {nombre}")

        QMessageBox.information(
            self,
            "¡Listo!",
            f"Documento guardado exitosamente:\n{ruta_final}"
        )

    def _on_guardar_cancelado(self):
        """Usuario presionó '← Volver al escaneo' en FaseGuardar."""
        if self._vista_guardar is not None:
            self._vista_guardar.close()
            self._vista_guardar.deleteLater()
            self._vista_guardar = None

        self.status.showMessage("Volviendo al escaneo…")
        self._abrir_escaneo(self._pagina_activa)

    def _on_escaneo_cancelado(self):
        """Usuario presionó '← Volver a páginas' en VistaEscaneo."""
        if self._vista_escaneo is not None:
            self._vista_escaneo.close()
            self._vista_escaneo.deleteLater()
            self._vista_escaneo = None
        self.status.showMessage("Escaneo cancelado — volviendo al grid de páginas.")
        self._iniciar_flujo_trabajo()

    def _on_preview_cancelado(self):
        if self._vista_preview is not None:
            self._vista_preview.close()
            self._vista_preview.deleteLater()
            self._vista_preview = None
        self.status.showMessage("Vista de páginas cerrada.")

    # ── Re‑abrir guardado ─────────────────────────────────────────────────

    def _reabrir_desde_boton(self):
        item = self._item_seleccionado()
        if item:
            self._reabrir_guardado(item)

    def _reabrir_guardado(self, item: "ItemGuardado"):
        if self._pdf_activo is not None:
            QMessageBox.information(
                self, "PDF en proceso",
                "Hay un trabajo activo en curso.\n"
                "Cancelá el trabajo actual antes de abrir otro."
            )
            return

        ruta = item.ruta
        if not ruta.exists():
            QMessageBox.warning(
                self, "Archivo no encontrado",
                f"El archivo ya no existe:\n{ruta}"
            )
            self.lista_guardados.takeItem(self.lista_guardados.row(item))
            self._actualizar_estado_vacio()
            return

        copia = CARPETA_TRABAJO / f"reedit_{ruta.name}"
        try:
            shutil.copy2(ruta, copia)
        except Exception as e:
            QMessageBox.critical(self, "Error al copiar", str(e))
            return

        self._activar_pdf(copia)
        self.status.showMessage(f"Re‑editando: {ruta.name}")

    # ── Enviar por correo ─────────────────────────────────────────────────

    def _enviar_correo(self):
        item = self._item_seleccionado()
        if not item:
            return

        if not item.ruta.exists():
            QMessageBox.warning(
                self, "Archivo no encontrado",
                f"No se encontró:\n{item.ruta}"
            )
            return

        try:
            from modules.fase4_email import enviar_documento
        except ImportError as e:
            QMessageBox.critical(self, "Error de módulo", str(e))
            return

        enviar_documento(
            pdf_firmado = item.ruta,
            config      = self.config,
            paginas     = [0],
            nombre_doc  = item.ruta.stem,
        )
        self.status.showMessage(
            f"Flujo de envío iniciado para: {item.ruta.name}"
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    ventana = VentanaPrincipal()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
