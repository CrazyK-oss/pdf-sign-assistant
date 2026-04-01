"""
PDF Sign Assistant — main.py
============================================================
Flujo principal:
  1. Pantalla de inicio: botón "Abrir PDF" + lista de trabajos guardados.
  2. Panel activo cuando hay un PDF en trabajo (cancelar / trabajar páginas).
  3. El panel activo delega a:
       fase1_preview → fase2_print → fase3_scan → fase_guardar
  4. Al confirmar se añade a la lista de guardados (con fecha/hora).
  5. Doble-clic en guardado → vuelve a abrir ese PDF para re-editar.
  6. Seleccionar guardado → habilita botones Editar y Enviar correo.
  7. Botón ⚙ → abre DialogoAjustes (correo emisor).
  8. Botón ☉/🌙 → alterna entre modo claro y oscuro.
  9. Botón 📂 → abre la carpeta de documentos firmados en el Explorador.

NOTA PyInstaller:
  - Todas las dependencias deben estar instaladas antes de buildear:
      pip install -r requirements.txt
  - Las rutas se resuelven vía modules.setup.get_base_dir() para
    compatibilidad entre modo script y modo .exe congelado.
"""

import os
import sys
import json
import shutil
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
    QMessageBox, QFrame, QSizePolicy, QStatusBar, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont

from modules.fase1_preview import VistaPrevisualizacion
from modules.setup import get_base_dir
from modules.theme import apply_theme, THEME, font_pt, current_mode

BASE_DIR        = get_base_dir()
CARPETA_TRABAJO = BASE_DIR / "pdfs_trabajo"
CARPETA_FIRMADO = BASE_DIR / "pdfs_firmados"
CONFIG_PATH     = BASE_DIR / "config.json"
CARPETA_TRABAJO.mkdir(exist_ok=True)
CARPETA_FIRMADO.mkdir(exist_ok=True)

# Limpiar carpeta temporal de envíos anteriores al iniciar
try:
    from modules.fase4_email import limpiar_temp_al_iniciar
    limpiar_temp_al_iniciar(CARPETA_FIRMADO)
except Exception:
    pass


# ── Utilidades UI ───────────────────────────────────────────────────────────────────

def _cargar_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _btn(
    texto: str, *,
    danger=False, secondary=False, ghost=False,
    min_w=0, height=36
) -> QPushButton:
    b = QPushButton(texto)
    b.setMinimumHeight(height)
    if min_w:
        b.setMinimumWidth(min_w)
    prop = "danger" if danger else "secondary" if secondary else "ghost" if ghost else None
    if prop:
        b.setProperty(prop, "true")
        b.style().unpolish(b)
        b.style().polish(b)
    return b


def _sep() -> QFrame:
    s = QFrame()
    s.setFrameShape(QFrame.Shape.HLine)
    s.setFrameShadow(QFrame.Shadow.Plain)
    return s


# ── Panel PDF activo ──────────────────────────────────────────────────────────────────

class PanelActivo(QFrame):
    def __init__(self, ruta: Path, on_trabajar, on_cancelar, parent=None):
        super().__init__(parent)
        self.setObjectName("panelActivo")
        self.ruta = ruta

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        fila_info = QHBoxLayout()
        fila_info.setSpacing(14)

        icono = QLabel("📄")
        icono.setFont(QFont("Segoe UI Emoji", font_pt(22)))
        icono.setFixedWidth(36)
        icono.setAlignment(Qt.AlignmentFlag.AlignTop)
        fila_info.addWidget(icono)

        col_info = QVBoxLayout()
        col_info.setSpacing(3)

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
        fila_btns.setSpacing(10)

        btn_trabajar = _btn("Trabajar páginas →", min_w=200, height=42)
        btn_trabajar.clicked.connect(on_trabajar)
        fila_btns.addWidget(btn_trabajar)
        fila_btns.addStretch()

        btn_cancelar = _btn("✕  Cancelar", danger=True, height=42)
        btn_cancelar.clicked.connect(on_cancelar)
        fila_btns.addWidget(btn_cancelar)

        lay.addLayout(fila_btns)


# ── Item de guardados ──────────────────────────────────────────────────────────────────

class ItemGuardado(QListWidgetItem):
    def __init__(self, ruta: Path):
        super().__init__()
        self.ruta = ruta
        try:
            ts    = ruta.stat().st_mtime
            fecha = datetime.fromtimestamp(ts).strftime("%d/%m/%Y  %H:%M")
        except Exception:
            fecha = ""
        self.setText(f"{ruta.name}\n{fecha}")
        self.setSizeHint(QSize(0, 58))
        self.setToolTip(str(ruta))


# ── Ventana principal ──────────────────────────────────────────────────────────────────

class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Sign Assistant")
        self.setMinimumSize(720, 600)
        self.config = _cargar_config()
        self._pdf_activo: Path | None = None
        self._pagina_activa: int = 0
        self._vista_preview  = None
        self._vista_escaneo  = None
        self._vista_guardar  = None
        self._build_ui()
        self._cargar_guardados_existentes()

    # ── Construcción de UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 22, 28, 16)
        root.setSpacing(0)

        # ─ Header
        header = QHBoxLayout()
        header.setSpacing(10)

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {THEME['primary']}; font-size: 10px;")
        dot.setFixedWidth(14)
        header.addWidget(dot)
        self._dot = dot

        lbl_titulo = QLabel("PDF Sign Assistant")
        lbl_titulo.setObjectName("appTitle")
        header.addWidget(lbl_titulo)
        header.addStretch()

        # Toggle tema ☉/🌙
        self.btn_tema = _btn("🌙", ghost=True, height=40)
        self.btn_tema.setFixedWidth(44)
        self.btn_tema.setToolTip("Cambiar a modo oscuro")
        self.btn_tema.clicked.connect(self._toggle_tema)
        header.addWidget(self.btn_tema)

        # Ajustes ⚙
        self.btn_ajustes = _btn("⚙", ghost=True, height=40)
        self.btn_ajustes.setFixedWidth(44)
        self.btn_ajustes.setToolTip("Ajustes")
        self.btn_ajustes.clicked.connect(self._abrir_ajustes)
        header.addWidget(self.btn_ajustes)

        # Abrir PDF
        self.btn_abrir = _btn("＋  Abrir PDF", min_w=150, height=40)
        self.btn_abrir.clicked.connect(self.abrir_pdf)
        header.addWidget(self.btn_abrir)

        root.addLayout(header)
        root.addSpacing(16)
        root.addWidget(_sep())
        root.addSpacing(16)

        # ─ Panel activo (oculto al inicio)
        self.panel_activo_container = QWidget()
        self.panel_activo_container.setVisible(False)
        self._lay_panel = QVBoxLayout(self.panel_activo_container)
        self._lay_panel.setContentsMargins(0, 0, 0, 0)
        self._lay_panel.setSpacing(0)
        root.addWidget(self.panel_activo_container)

        self._sep_panel = _sep()
        self._sep_panel.setVisible(False)
        root.addWidget(self._sep_panel)

        # ─ Sección: guardados
        root.addSpacing(14)
        hdr_guard = QHBoxLayout()
        lbl_g = QLabel("TRABAJOS GUARDADOS")
        lbl_g.setObjectName("seccion")
        hdr_guard.addWidget(lbl_g)
        hdr_guard.addStretch()
        self.lbl_contador = QLabel("")
        self.lbl_contador.setObjectName("fechaItem")
        hdr_guard.addWidget(self.lbl_contador)
        root.addLayout(hdr_guard)
        root.addSpacing(8)

        # Lista
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
        lay_vacio.setContentsMargins(28, 36, 28, 36)
        lay_vacio.setSpacing(10)

        icono_v = QLabel("📋")
        icono_v.setFont(QFont("Segoe UI Emoji", font_pt(28)))
        icono_v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay_vacio.addWidget(icono_v)

        lbl_v_t = QLabel("Sin documentos modificados todavía")
        lbl_v_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_v_t.setStyleSheet("font-size: 14px; font-weight: 600;")
        lay_vacio.addWidget(lbl_v_t)

        lbl_v_s = QLabel(
            "Abrí un PDF con el botón de arriba para comenzar.\n"
            "Los documentos que guardés aparecerán aquí."
        )
        lbl_v_s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_v_s.setObjectName("fechaItem")
        lbl_v_s.setWordWrap(True)
        lay_vacio.addWidget(lbl_v_s)

        root.addWidget(self.panel_vacio)

        # ─ Acciones sobre guardados
        root.addSpacing(10)
        fila_acc = QHBoxLayout()
        fila_acc.setSpacing(8)

        self.btn_reabrir = _btn("✏️  Editar seleccionado", secondary=True, height=36)
        self.btn_reabrir.clicked.connect(self._reabrir_desde_boton)
        self.btn_reabrir.setEnabled(False)
        fila_acc.addWidget(self.btn_reabrir)

        self.btn_email = _btn("✉️  Enviar por correo", secondary=True, height=36)
        self.btn_email.clicked.connect(self._enviar_correo)
        self.btn_email.setEnabled(False)
        fila_acc.addWidget(self.btn_email)

        fila_acc.addStretch()

        # ─ Botón abrir carpeta de firmados
        self.btn_carpeta = _btn("📂  Abrir carpeta", ghost=True, height=36)
        self.btn_carpeta.setToolTip(str(CARPETA_FIRMADO))
        self.btn_carpeta.clicked.connect(self._abrir_carpeta_firmados)
        fila_acc.addWidget(self.btn_carpeta)

        root.addLayout(fila_acc)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Listo — abrí un PDF para comenzar.")

    # ── Toggle tema ──────────────────────────────────────────────────────────────────

    def _toggle_tema(self):
        nuevo = "dark" if current_mode() == "light" else "light"
        apply_theme(QApplication.instance(), nuevo)
        self.btn_tema.setText("☉️" if nuevo == "dark" else "🌙")
        self.btn_tema.setToolTip(
            "Cambiar a modo claro" if nuevo == "dark" else "Cambiar a modo oscuro"
        )
        self._dot.setStyleSheet(f"color: {THEME['primary']}; font-size: 10px;")
        self.status.showMessage(
            f"Tema {'oscuro' if nuevo == 'dark' else 'claro'} activado."
        )

    # ── Estado vacío / lista ─────────────────────────────────────────────────────────────────

    def _actualizar_estado_vacio(self):
        count = self.lista_guardados.count()
        tiene = count > 0
        self.lista_guardados.setVisible(tiene)
        self.panel_vacio.setVisible(not tiene)
        self.lbl_contador.setText(
            f"{count} documento{'s' if count != 1 else ''}" if tiene else ""
        )

    def _cargar_guardados_existentes(self):
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

    # ── Selección ─────────────────────────────────────────────────────────────────────

    def _on_seleccion_guardado(self):
        tiene = bool(self.lista_guardados.selectedItems())
        self.btn_reabrir.setEnabled(tiene)
        self.btn_email.setEnabled(tiene)

    def _item_seleccionado(self) -> "ItemGuardado | None":
        items = self.lista_guardados.selectedItems()
        return items[0] if items else None

    # ── Ajustes ────────────────────────────────────────────────────────────────────────

    def _abrir_ajustes(self):
        from modules.settings import DialogoAjustes
        dlg = DialogoAjustes(config_path=CONFIG_PATH, config=self.config, parent=self)
        if dlg.exec():
            self.config = dlg.config
            self.status.showMessage(
                f"Ajustes guardados — correo: {self.config.get('email_user', '')}"
            )

    # ── Abrir PDF ────────────────────────────────────────────────────────────────────────

    def abrir_pdf(self):
        if self._pdf_activo is not None:
            QMessageBox.information(
                self, "PDF en proceso",
                f"Ya hay un PDF en trabajo:\n{self._pdf_activo.name}\n\n"
                "Cancelá o finalizá el trabajo actual antes de abrir otro."
            )
            return

        ruta_str, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar PDF", str(Path.home()), "Archivos PDF (*.pdf)"
        )
        if not ruta_str:
            return

        origen  = Path(ruta_str)
        destino = CARPETA_TRABAJO / origen.name
        if destino.exists():
            ts      = datetime.now().strftime("%H%M%S")
            destino = CARPETA_TRABAJO / f"{origen.stem}_{ts}{origen.suffix}"

        try:
            shutil.copy2(origen, destino)
        except Exception as e:
            QMessageBox.critical(self, "Error al copiar", str(e))
            return

        self._activar_pdf(destino)
        self.status.showMessage(f"PDF cargado: {destino.name}")

    def _activar_pdf(self, ruta: Path):
        self._pdf_activo = ruta
        while self._lay_panel.count():
            w = self._lay_panel.takeAt(0).widget()
            if w:
                w.deleteLater()
        panel = PanelActivo(ruta, on_trabajar=self._iniciar_flujo_trabajo,
                            on_cancelar=self._cancelar_trabajo)
        self._lay_panel.addWidget(panel)
        self.panel_activo_container.setVisible(True)
        self._sep_panel.setVisible(True)
        self.btn_abrir.setEnabled(False)

    # ── Cancelar trabajo ──────────────────────────────────────────────────────────────────

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
        self._pdf_activo   = None
        self._pagina_activa = 0
        while self._lay_panel.count():
            w = self._lay_panel.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.panel_activo_container.setVisible(False)
        self._sep_panel.setVisible(False)
        self.btn_abrir.setEnabled(True)

    def _cerrar_vistas_abiertas(self):
        for attr in ("_vista_preview", "_vista_escaneo", "_vista_guardar"):
            v = getattr(self, attr, None)
            if v:
                v.close()
                v.deleteLater()
                setattr(self, attr, None)

    # ── Flujo de trabajo ─────────────────────────────────────────────────────────────────

    def _iniciar_flujo_trabajo(self):
        if self._pdf_activo is None:
            return
        if self._vista_preview:
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
        self._pagina_activa = num_pagina
        if self._vista_preview:
            self._vista_preview.close()
            self._vista_preview.deleteLater()
            self._vista_preview = None
        from modules.fase2_print import ImpresionPagina
        imprimio = ImpresionPagina.imprimir(str(self._pdf_activo), num_pagina, parent=self)
        if not imprimio:
            self.status.showMessage("Impresión cancelada.")
            self._iniciar_flujo_trabajo()
            return
        self.status.showMessage(f"Página {num_pagina + 1} enviada a impresora…")
        self._abrir_escaneo(num_pagina)

    def _abrir_escaneo(self, num_pagina: int):
        if self._vista_escaneo:
            self._vista_escaneo.close()
            self._vista_escaneo.deleteLater()
            self._vista_escaneo = None
        from modules.fase3_scan import VistaEscaneo
        self._vista_escaneo = VistaEscaneo(str(self._pdf_activo), num_pagina, parent=self)
        self._vista_escaneo.setWindowTitle("PDF Sign Assistant — Escanear página")
        self._vista_escaneo.resize(820, 560)
        self._vista_escaneo.imagen_lista.connect(self._on_imagen_escaneada)
        self._vista_escaneo.cancelar.connect(self._on_escaneo_cancelado)
        self._vista_escaneo.show()

    def _on_imagen_escaneada(self, ruta_imagen: str):
        if self._vista_escaneo:
            self._vista_escaneo.close()
            self._vista_escaneo.deleteLater()
            self._vista_escaneo = None
        self._abrir_guardar(ruta_imagen)

    def _abrir_guardar(self, ruta_imagen: str):
        if self._vista_guardar:
            self._vista_guardar.close()
            self._vista_guardar.deleteLater()
            self._vista_guardar = None
        from modules.fase_guardar import FaseGuardar
        self._vista_guardar = FaseGuardar(
            ruta_pdf=self._pdf_activo, ruta_imagen=ruta_imagen,
            num_pagina=self._pagina_activa, carpeta_firmados=CARPETA_FIRMADO,
            parent=self,
        )
        self._vista_guardar.setWindowTitle("PDF Sign Assistant — Guardar documento")
        self._vista_guardar.resize(780, 520)
        self._vista_guardar.guardado_listo.connect(self._on_guardado_listo)
        self._vista_guardar.cancelado.connect(self._on_guardar_cancelado)
        self._vista_guardar.show()

    def _on_guardado_listo(self, ruta_final):
        if self._vista_guardar:
            self._vista_guardar.close()
            self._vista_guardar.deleteLater()
            self._vista_guardar = None
        try:
            if self._pdf_activo and self._pdf_activo.exists():
                self._pdf_activo.unlink()
        except Exception:
            pass
        nombre = Path(ruta_final).name
        self._desactivar_panel()
        self._agregar_item_guardado(Path(ruta_final))
        self.status.showMessage(f"✅  Guardado: {nombre}")
        QMessageBox.information(self, "¡Listo!", f"Documento guardado:\n{ruta_final}")

    def _on_guardar_cancelado(self):
        if self._vista_guardar:
            self._vista_guardar.close()
            self._vista_guardar.deleteLater()
            self._vista_guardar = None
        self._abrir_escaneo(self._pagina_activa)

    def _on_escaneo_cancelado(self):
        if self._vista_escaneo:
            self._vista_escaneo.close()
            self._vista_escaneo.deleteLater()
            self._vista_escaneo = None
        self._iniciar_flujo_trabajo()

    def _on_preview_cancelado(self):
        if self._vista_preview:
            self._vista_preview.close()
            self._vista_preview.deleteLater()
            self._vista_preview = None
        self.status.showMessage("Vista de páginas cerrada.")

    # ── Re-abrir guardado ──────────────────────────────────────────────────────────────────

    def _reabrir_desde_boton(self):
        item = self._item_seleccionado()
        if item:
            self._reabrir_guardado(item)

    def _reabrir_guardado(self, item: "ItemGuardado"):
        if self._pdf_activo is not None:
            QMessageBox.information(self, "PDF en proceso",
                "Cancelá el trabajo actual antes de abrir otro.")
            return
        ruta = item.ruta
        if not ruta.exists():
            QMessageBox.warning(self, "Archivo no encontrado",
                f"El archivo ya no existe:\n{ruta}")
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
        self.status.showMessage(f"Re-editando: {ruta.name}")

    # ── Enviar correo ──────────────────────────────────────────────────────────────────────

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
        enviar_documento(
            pdf_firmado=item.ruta,
            carpeta_firmados=CARPETA_FIRMADO,
            config=self.config,
            paginas=[0],
            nombre_doc=item.ruta.stem,
        )
        self.status.showMessage(f"Flujo de envío iniciado: {item.ruta.name}")

    # ── Abrir carpeta de firmados ────────────────────────────────────────────────────────

    def _abrir_carpeta_firmados(self):
        ruta = CARPETA_FIRMADO
        ruta.mkdir(exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(ruta))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(ruta)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(ruta)])
        self.status.showMessage(f"Carpeta abierta: {ruta}")


# ── Entry point ──────────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    apply_theme(app, "light")
    ventana = VentanaPrincipal()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
