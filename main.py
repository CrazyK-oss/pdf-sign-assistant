"""
PDF Sign Assistant — main.py  (Parte 1 del refactor)
=====================================================
Flujo principal:
  1. Pantalla de inicio: botón "Abrir PDF" + lista de trabajos ya guardados.
  2. Cuando hay un PDF en trabajo: se muestra el panel activo con botón Cancelar.
     La lista de guardados sigue visible debajo.
  3. El panel activo delega a fase1_preview → fase2_print → fase3_scan → fase_guardar.
  4. Al confirmar se añade a la lista de guardados.
  5. Doble‑clic en guardado → vuelve a abrir ese PDF para re‑editar.
  6. Botón "Enviar correo" en guardado → llama a fase4_email.enviar_documento.
"""

import sys
import os
import json
import shutil
import subprocess
from pathlib import Path
from dotenv import load_dotenv

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
        QInputDialog,
    )
    from PyQt6.QtCore import Qt, QSize
    from PyQt6.QtGui import QFont, QIcon, QColor
except ImportError:
    _instalar_deps()
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
        QMessageBox, QFrame, QSizePolicy, QStatusBar, QAbstractItemView,
        QInputDialog,
    )
    from PyQt6.QtCore import Qt, QSize
    from PyQt6.QtGui import QFont, QIcon, QColor

load_dotenv(Path(__file__).parent / ".env")

BASE_DIR         = Path(__file__).parent
CARPETA_TRABAJO  = BASE_DIR / "pdfs_trabajo"
CARPETA_FIRMADO  = BASE_DIR / "pdfs_firmados"
CONFIG_PATH      = BASE_DIR / "config.json"
CARPETA_TRABAJO.mkdir(exist_ok=True)
CARPETA_FIRMADO.mkdir(exist_ok=True)

# ── Paleta de colores (PyQt‑friendly) ────────────────────────────────────────
C_BG          = "#f7f6f2"
C_SURFACE     = "#f3f0ec"
C_BORDER      = "#d4d1ca"
C_TEXT        = "#28251d"
C_MUTED       = "#7a7974"
C_PRIMARY     = "#01696f"
C_PRIMARY_H   = "#0c4e54"
C_DANGER      = "#a13544"
C_DANGER_H    = "#782b33"
C_SUCCESS     = "#437a22"
C_SUCCESS_H   = "#2e5c10"
C_WARNING_BG  = "#fef9ec"
C_WARNING_BD  = "#e8c76a"
C_ACTIVE_BG   = "#e8f4f5"
C_ACTIVE_BD   = "#01696f"

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
QPushButton:hover  {{ background-color: {C_PRIMARY_H}; }}
QPushButton:pressed {{ background-color: #0f3638; }}
QPushButton:disabled {{
    background-color: {C_BORDER};
    color: {C_MUTED};
}}

/* ── Botón peligro ── */
QPushButton[danger="true"] {{
    background-color: {C_DANGER};
}}
QPushButton[danger="true"]:hover {{ background-color: {C_DANGER_H}; }}

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
    background-color: #edeae5;
}}
QListWidget::item:selected {{
    background-color: #cedcd8;
    color: {C_TEXT};
}}

/* ── Panel de trabajo activo ── */
QFrame#panelActivo {{
    background-color: {C_ACTIVE_BG};
    border: 1.5px solid {C_ACTIVE_BD};
    border-radius: 10px;
}}

/* ── Etiqueta de sección ── */
QLabel#seccion {{
    font-size: 11px;
    font-weight: 700;
    color: {C_MUTED};
    letter-spacing: 1px;
    text-transform: uppercase;
}}

/* ── Nombre del PDF activo ── */
QLabel#nombreActivo {{
    font-size: 15px;
    font-weight: 600;
    color: {C_TEXT};
}}

/* ── Status bar ── */
QStatusBar {{
    background-color: {C_SURFACE};
    border-top: 1px solid {C_BORDER};
    font-size: 12px;
    color: {C_MUTED};
    padding: 2px 8px;
}}

/* ── Separador ── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {C_BORDER};
}}
"""


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


class PanelActivo(QFrame):
    """
    Panel que se muestra cuando hay un PDF en proceso.
    Contiene:  nombre del archivo · botón Trabajar · botón Cancelar
    """
    def __init__(self, ruta: Path, on_trabajar, on_cancelar, parent=None):
        super().__init__(parent)
        self.setObjectName("panelActivo")
        self.ruta = ruta

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        # Fila superior: icono + nombre
        fila_nombre = QHBoxLayout()
        icono = QLabel("📄")
        icono.setFont(QFont("Segoe UI", 20))
        fila_nombre.addWidget(icono)

        col_info = QVBoxLayout()
        lbl_tag = QLabel("PDF EN TRABAJO")
        lbl_tag.setObjectName("seccion")
        col_info.addWidget(lbl_tag)

        lbl_nombre = QLabel(ruta.name)
        lbl_nombre.setObjectName("nombreActivo")
        lbl_nombre.setWordWrap(True)
        col_info.addWidget(lbl_nombre)

        fila_nombre.addLayout(col_info)
        fila_nombre.addStretch()
        lay.addLayout(fila_nombre)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        # Botones
        fila_btns = QHBoxLayout()
        fila_btns.setSpacing(8)

        btn_trabajar = _btn("Abrir y trabajar páginas →", min_w=220, height=40)
        btn_trabajar.clicked.connect(on_trabajar)
        fila_btns.addWidget(btn_trabajar)

        fila_btns.addStretch()

        btn_cancelar = _btn("✕  Cancelar / Salir del PDF", danger=True, height=40)
        btn_cancelar.clicked.connect(on_cancelar)
        fila_btns.addWidget(btn_cancelar)

        lay.addLayout(fila_btns)


class ItemGuardado(QListWidgetItem):
    """Item de la lista de PDFs ya modificados."""
    def __init__(self, ruta: Path):
        super().__init__()
        self.ruta = ruta
        self.setText(ruta.name)
        self.setSizeHint(QSize(0, 52))
        self.setToolTip(str(ruta))


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Sign Assistant")
        self.setMinimumSize(680, 560)
        self.config = _cargar_config()
        self._pdf_activo: Path | None = None
        self._build_ui()
        self._cargar_guardados_existentes()

    # ── Construcción UI ───────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(STYLESHEET)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(14)

        # ── Header ──────────────────────────────────────────────────────
        header = QHBoxLayout()

        lbl_titulo = QLabel("PDF Sign Assistant")
        lbl_titulo.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        header.addWidget(lbl_titulo)
        header.addStretch()

        self.btn_abrir = _btn("+ Abrir PDF", min_w=130, height=40)
        self.btn_abrir.clicked.connect(self.abrir_pdf)
        header.addWidget(self.btn_abrir)

        root.addLayout(header)

        # ── Separador ──────────────────────────────────────────────────
        sep_top = QFrame()
        sep_top.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep_top)

        # ── Panel activo (oculto al inicio) ────────────────────────────
        self.panel_activo_container = QWidget()
        self.panel_activo_container.setVisible(False)
        self._lay_panel_activo = QVBoxLayout(self.panel_activo_container)
        self._lay_panel_activo.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.panel_activo_container)

        # ── Sección: trabajos guardados ─────────────────────────────────
        lbl_guardados = QLabel("TRABAJOS GUARDADOS")
        lbl_guardados.setObjectName("seccion")
        root.addWidget(lbl_guardados)

        self.lista_guardados = QListWidget()
        self.lista_guardados.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.lista_guardados.itemDoubleClicked.connect(self._reabrir_guardado)
        self.lista_guardados.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self.lista_guardados)

        # ── Estado vacío ────────────────────────────────────────────────
        self.lbl_vacio = QLabel(
            "Todavía no hay documentos modificados.\n"
            "Abrí un PDF con el botón de arriba para empezar."
        )
        self.lbl_vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_vacio.setStyleSheet(f"color: {C_MUTED}; font-size: 13px;")
        self.lbl_vacio.setWordWrap(True)
        root.addWidget(self.lbl_vacio)

        # ── Barra de acciones sobre guardados ───────────────────────────
        fila_acciones = QHBoxLayout()
        fila_acciones.setSpacing(8)

        self.btn_reabrir = _btn("Editar seleccionado", secondary=True, height=36)
        self.btn_reabrir.clicked.connect(self._reabrir_desde_boton)
        self.btn_reabrir.setEnabled(False)
        fila_acciones.addWidget(self.btn_reabrir)

        self.btn_email = _btn("Enviar por correo", secondary=True, height=36)
        self.btn_email.clicked.connect(self._enviar_correo)
        self.btn_email.setEnabled(False)
        fila_acciones.addWidget(self.btn_email)

        fila_acciones.addStretch()
        root.addLayout(fila_acciones)

        self.lista_guardados.itemSelectionChanged.connect(self._on_seleccion_guardado)

        # ── Status bar ──────────────────────────────────────────────────
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Listo — abrí un PDF para comenzar.")

    # ── Estado vacío / lista ──────────────────────────────────────────────

    def _actualizar_estado_vacio(self):
        tiene_items = self.lista_guardados.count() > 0
        self.lista_guardados.setVisible(tiene_items)
        self.lbl_vacio.setVisible(not tiene_items)

    def _cargar_guardados_existentes(self):
        """Precarga PDFs ya presentes en pdfs_firmados/ al arrancar."""
        for pdf in sorted(CARPETA_FIRMADO.glob("*.pdf")):
            self._agregar_item_guardado(pdf, scroll=False)
        self._actualizar_estado_vacio()

    def _agregar_item_guardado(self, ruta: Path, scroll=True):
        item = ItemGuardado(ruta)
        self.lista_guardados.addItem(item)
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
        if self._pdf_activo is not None:
            QMessageBox.information(
                self, "PDF en proceso",
                f"Ya hay un PDF en trabajo:\n{self._pdf_activo.name}\n\n"
                "Cancela o finaliza el trabajo actual antes de abrir otro."
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
            destino = CARPETA_TRABAJO / f"{origen.stem}_copia{origen.suffix}"

        try:
            shutil.copy2(origen, destino)
        except Exception as e:
            QMessageBox.critical(self, "Error al copiar", str(e))
            return

        self._activar_pdf(destino)
        self.status.showMessage(f"PDF cargado: {destino.name}")

    def _activar_pdf(self, ruta: Path):
        """Muestra el panel activo con el PDF indicado."""
        self._pdf_activo = ruta

        # Limpiar panel anterior si existía
        while self._lay_panel_activo.count():
            w = self._lay_panel_activo.takeAt(0).widget()
            if w:
                w.deleteLater()

        panel = PanelActivo(
            ruta,
            on_trabajar=self._iniciar_flujo_trabajo,
            on_cancelar=self._cancelar_trabajo,
        )
        self._lay_panel_activo.addWidget(panel)
        self.panel_activo_container.setVisible(True)
        self.btn_abrir.setEnabled(False)

    # ── Cancelar trabajo ─────────────────────────────────────────────────

    def _cancelar_trabajo(self):
        if self._pdf_activo is None:
            return
        resp = QMessageBox.question(
            self, "Cancelar trabajo",
            f"¿Seguro que querés salir de:\n{self._pdf_activo.name}?\n\n"
            "Los cambios no guardados se perderán.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        # Intentar eliminar la copia de trabajo
        try:
            if self._pdf_activo.exists():
                self._pdf_activo.unlink()
        except Exception:
            pass

        self._desactivar_panel()
        self.status.showMessage("Trabajo cancelado.")

    def _desactivar_panel(self):
        """Oculta el panel activo y libera el PDF activo."""
        self._pdf_activo = None
        while self._lay_panel_activo.count():
            w = self._lay_panel_activo.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.panel_activo_container.setVisible(False)
        self.btn_abrir.setEnabled(True)

    # ── Flujo de trabajo principal ────────────────────────────────────────

    def _iniciar_flujo_trabajo(self):
        """
        Punto de entrada al flujo:
          fase1 → seleccionar página
          fase2 → imprimir
          fase3 → escanear/adjuntar imagen
          fase_guardar → confirmar y guardar   (Parte 4, próxima iteración)
        """
        if self._pdf_activo is None:
            return

        # ── Fase 1: selección de página ──────────────────────────────────
        try:
            from modules.fase1_preview import seleccionar_paginas
        except ImportError as e:
            QMessageBox.critical(self, "Error de módulo", str(e))
            return

        paginas = seleccionar_paginas(self._pdf_activo)
        if paginas is None:
            self.status.showMessage("Selección de páginas cancelada.")
            return

        # Por ahora manejamos solo la primera página seleccionada
        pagina_idx = paginas[0]
        self.status.showMessage(
            f"Página {pagina_idx + 1} seleccionada — preparando impresión…"
        )

        # ── Fase 2: imprimir ─────────────────────────────────────────────
        try:
            from modules.fase2_print import imprimir_pagina
        except ImportError as e:
            QMessageBox.critical(self, "Error de módulo", str(e))
            return

        imprimio = imprimir_pagina(self._pdf_activo, pagina_idx)
        if not imprimio:
            self.status.showMessage("Impresión cancelada.")
            return

        self.status.showMessage("Página enviada a impresora — esperando escaneo…")

        # ── Fase 3: escanear / adjuntar ──────────────────────────────────
        try:
            from modules.fase3_scan import obtener_imagen_firmada
        except ImportError as e:
            QMessageBox.critical(self, "Error de módulo", str(e))
            return

        imagen_pdf = obtener_imagen_firmada(self._pdf_activo, pagina_idx)
        if imagen_pdf is None:
            self.status.showMessage("Escaneo cancelado.")
            return

        self.status.showMessage("Imagen recibida — abriendo confirmación…")

        # ── Fase 4: guardar (Parte 4, pendiente de implementar) ──────────
        # Por ahora llamamos a _finalizar_trabajo directamente con un nombre
        self._finalizar_trabajo(imagen_pdf, pagina_idx)

    # ── Finalizar y guardar ───────────────────────────────────────────────

    def _finalizar_trabajo(self, imagen_pdf: Path, pagina_idx: int):
        """
        Reemplaza la página, pregunta nombre, mueve a firmados y
        agrega a la lista de guardados.
        Esta lógica será expandida en la Parte 4 (fase_guardar.py).
        """
        if self._pdf_activo is None:
            return

        nombre_sugerido = self._pdf_activo.stem
        nombre, ok = QInputDialog.getText(
            self, "Guardar documento",
            "¿Con qué nombre querés guardar el PDF modificado?",
            text=nombre_sugerido,
        )
        if not ok or not nombre.strip():
            return

        nombre = nombre.strip()
        if not nombre.lower().endswith(".pdf"):
            nombre += ".pdf"

        destino_final = CARPETA_FIRMADO / nombre

        # Reemplazo básico de página usando pypdf (si está disponible) o PyPDF2
        try:
            self._reemplazar_pagina(self._pdf_activo, imagen_pdf, pagina_idx, destino_final)
        except Exception as e:
            QMessageBox.critical(self, "Error al guardar", str(e))
            return

        self._desactivar_panel()
        self._agregar_item_guardado(destino_final)
        self.status.showMessage(f"✅  Guardado: {nombre}")

        QMessageBox.information(
            self, "¡Listo!",
            f"Documento guardado exitosamente:\n{destino_final}"
        )

    def _reemplazar_pagina(self, pdf_original: Path, nueva_pag_pdf: Path,
                           idx: int, destino: Path):
        """Reemplaza la página idx del pdf_original con nueva_pag_pdf."""
        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError:
            from PyPDF2 import PdfReader, PdfWriter  # fallback

        lector_orig = PdfReader(str(pdf_original))
        lector_nueva = PdfReader(str(nueva_pag_pdf))
        writer = PdfWriter()

        for i, pag in enumerate(lector_orig.pages):
            if i == idx:
                writer.add_page(lector_nueva.pages[0])
            else:
                writer.add_page(pag)

        with open(destino, "wb") as f:
            writer.write(f)

    # ── Re‑abrir guardado ────────────────────────────────────────────────

    def _reabrir_desde_boton(self):
        item = self._item_seleccionado()
        if item:
            self._reabrir_guardado(item)

    def _reabrir_guardado(self, item: "ItemGuardado"):
        if self._pdf_activo is not None:
            QMessageBox.information(
                self, "PDF en proceso",
                "Hay un trabajo activo en curso.\n"
                "Cancela el trabajo actual antes de abrir otro."
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

        # Copiar a carpeta de trabajo para no tocar el original guardado
        copia = CARPETA_TRABAJO / f"reedit_{ruta.name}"
        try:
            shutil.copy2(ruta, copia)
        except Exception as e:
            QMessageBox.critical(self, "Error al copiar", str(e))
            return

        self._activar_pdf(copia)
        self.status.showMessage(f"Re‑editando: {ruta.name}")

    # ── Enviar por correo ────────────────────────────────────────────────

    def _enviar_correo(self):
        item = self._item_seleccionado()
        if not item:
            return

        if not item.ruta.exists():
            QMessageBox.warning(self, "Archivo no encontrado",
                                f"No se encontró:\n{item.ruta}")
            return

        try:
            from modules.fase4_email import enviar_documento
        except ImportError as e:
            QMessageBox.critical(self, "Error de módulo", str(e))
            return

        # fase4_email espera: pdf_firmado, config, paginas, nombre_doc
        # Como no sabemos qué páginas se modificaron en el re‑edit,
        # pasamos [0] como placeholder; la fase4 lo usa solo para el resumen.
        enviar_documento(
            pdf_firmado=item.ruta,
            config=self.config,
            paginas=[0],
            nombre_doc=item.ruta.stem,
        )
        self.status.showMessage(f"Flujo de envío iniciado para: {item.ruta.name}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    ventana = VentanaPrincipal()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
