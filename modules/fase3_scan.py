"""
modules/fase3_scan.py
============================================================
Fase 3: stand-by post-impresión. Digitalización directa vía WIA
(Windows Image Acquisition) o carga manual de la imagen firmada.

Cambios de esta versión
-----------------------
* Todo el estilo sale del tema (antes tenía ~15 stylesheets inline con
  colores fijos, por lo que la pantalla quedaba en claro aunque la app
  estuviera en modo oscuro).
* Se corrige el bug de los recuadros: los paneles declaraban
  `QFrame { border… }`, y como QLabel hereda de QFrame, cada etiqueta
  hija dibujaba su propio borde.
* Layout responsive: los dos paneles se apilan en vertical cuando la
  ventana es angosta, y el cuerpo va dentro de un scroll.
* La ventana ya no se dibuja como widget hijo de la ventana principal
  (le faltaba el flag Qt.Window).
* closeEvent no bloquea la UI esperando al escáner: el worker WIA sigue
  vivo por su cuenta y se limpia solo al terminar.
* Sólo borra los temporales que generó esta instancia.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from modules.theme import SIZE, SPACE, repolish, theme_signals
from modules.ui import (
    AreaScroll,
    BarraInferior,
    BarraSuperior,
    FilaAdaptable,
    boton,
    etiqueta,
    tarjeta,
)

EXTENSIONES_IMG = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp")
PREFIJO_TEMP = "pdf_sign_scan_"

# Los workers WIA se registran acá para que sigan vivos aunque la vista
# se cierre: destruir un QThread en ejecución revienta el proceso.
_WORKERS_VIVOS: set[QThread] = set()


# ─────────────────────────────────────────────────────────────────────────
#  Worker: lanza el diálogo WIA en hilo aparte
# ─────────────────────────────────────────────────────────────────────────
class WIAScanWorker(QThread):
    scan_completado = pyqtSignal(str)
    scan_cancelado  = pyqtSignal()
    scan_error      = pyqtSignal(str)

    # DPI objetivo. 300 alcanza para documentos simples; 600 se recomienda
    # cuando hay sellos húmedos o firmas con detalle fino.
    DPI_SCAN = 600

    def run(self):
        try:
            import win32com.client

            wia = win32com.client.Dispatch("WIA.CommonDialog")

            # ShowAcquireImage(
            #   DeviceType:         1 = Scanner
            #   Intent:             1 = Color
            #   Bias:               4 = MaximumQuality
            #   FormatID:           PNG sin pérdida
            #   AlwaysSelectDevice: False (usa el escáner por defecto)
            #   UseCommonUI:        True  (diálogo completo de WIA)
            #   CancelError:        True  (excepción si el usuario cancela)
            # )
            img_wia = wia.ShowAcquireImage(
                1, 1, 4,
                "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}",  # PNG
                False, True, True,
            )

            # Algunos escáneres exponen la resolución como propiedad WIA
            # (6147 = horizontal, 6148 = vertical). Si el driver no la
            # publica, el usuario ya pudo elegirla en el diálogo.
            try:
                img_wia.Properties("6147").Value = self.DPI_SCAN
                img_wia.Properties("6148").Value = self.DPI_SCAN
            except Exception:
                pass

            nombre = f"{PREFIJO_TEMP}{uuid.uuid4().hex[:8]}.png"
            ruta_destino = os.path.join(tempfile.gettempdir(), nombre)
            img_wia.SaveFile(ruta_destino)
            self.scan_completado.emit(ruta_destino)

        except Exception as e:                       # noqa: BLE001
            msg = str(e).lower()
            if any(x in msg for x in ("cancel", "0x80210003", "user cancel")):
                self.scan_cancelado.emit()
            else:
                self.scan_error.emit(str(e))


# ─────────────────────────────────────────────────────────────────────────
#  Zona de drag & drop
# ─────────────────────────────────────────────────────────────────────────
class ZonaDrop(QFrame):
    imagen_soltada = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("zonaDrop")
        self.setAcceptDrops(True)
        self.setMinimumHeight(112)
        self.setProperty("activo", "false")

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(SPACE["xs"])

        self.lbl_icono = etiqueta("⬇", rol="hint", align=Qt.AlignmentFlag.AlignCenter)
        self.lbl_icono.setStyleSheet("font-size: 24px;")
        lay.addWidget(self.lbl_icono)

        lay.addWidget(etiqueta("Arrastrá una imagen acá", rol="hint",
                               align=Qt.AlignmentFlag.AlignCenter))

    def _set_activo(self, activo: bool):
        self.setProperty("activo", "true" if activo else "false")
        repolish(self)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            url = e.mimeData().urls()[0].toLocalFile()
            if url.lower().endswith(EXTENSIONES_IMG):
                e.acceptProposedAction()
                self._set_activo(True)
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        self._set_activo(False)

    def dropEvent(self, e: QDropEvent):
        self._set_activo(False)
        if e.mimeData().hasUrls():
            self.imagen_soltada.emit(e.mimeData().urls()[0].toLocalFile())


# ─────────────────────────────────────────────────────────────────────────
#  Vista principal de la Fase 3
# ─────────────────────────────────────────────────────────────────────────
class VistaEscaneo(QWidget):
    """
    Señales:
      imagen_lista(str)  → ruta de la imagen para reemplazar la página
      cancelar()         → volver al grid de páginas
    """

    imagen_lista = pyqtSignal(str)
    cancelar     = pyqtSignal()

    def __init__(self, ruta_pdf: str, num_pagina: int, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setObjectName("pantalla")
        self.setMinimumSize(480, 460)

        self.ruta_pdf = ruta_pdf
        self.num_pagina = num_pagina
        self._ruta_img: str | None = None
        self._worker: WIAScanWorker | None = None
        self._imagen_entregada = False
        self._temporales: list[str] = []      # sólo los creados por esta vista

        self._construir_ui()
        theme_signals.changed.connect(self._on_tema_cambiado)

    # ── Construcción ───────────────────────────────────────────────────
    def _construir_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        nombre = os.path.basename(self.ruta_pdf)
        cab = BarraSuperior(f"Escanear  ·  Página {self.num_pagina + 1}  ·  {nombre}")
        cab.agregar(boton("←  Volver a páginas", variant="ghost",
                          tooltip="Volver al listado de páginas (Esc)",
                          on_click=self.cancelar.emit))
        raiz.addWidget(cab)

        cuerpo = AreaScroll(margenes=(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"]))
        lay = cuerpo.lay

        lay.addWidget(etiqueta(
            f"La página {self.num_pagina + 1} fue enviada a la impresora. "
            "Cuando tengas la hoja firmada, escaneala con el botón de abajo "
            "o cargá la imagen manualmente.",
            rol="cuerpo", wrap=True,
        ))

        badge = etiqueta(
            f"💡  El escaneo WIA se hace en color a {WIAScanWorker.DPI_SCAN} DPI "
            "(máxima calidad). Podés ajustarlo en el diálogo del escáner.",
            rol="badge", wrap=True,
        )
        lay.addWidget(badge)

        # Dos paneles que se apilan en pantallas angostas
        self.fila_paneles = FilaAdaptable(breakpoint_px=700, spacing=SPACE["md"])
        self.fila_paneles.agregar(self._panel_wia(), 1)
        self.fila_paneles.agregar(self._panel_manual(), 1)
        lay.addWidget(self.fila_paneles)

        lay.addWidget(self._panel_preview())
        lay.addStretch()
        raiz.addWidget(cuerpo, 1)

        self.pie = BarraInferior("Esperando imagen…")
        self.btn_usar = boton("Usar esta imagen  →", height=SIZE["btn_lg"],
                              enabled=False, on_click=self._on_usar_imagen)
        self.pie.agregar(self.btn_usar)
        raiz.addWidget(self.pie)

    def _panel_wia(self) -> QFrame:
        panel, lay = tarjeta(padding=SPACE["lg"], spacing=SPACE["sm"])
        lay.addWidget(etiqueta("Digitalizar con el escáner", rol="subtitulo"))
        lay.addWidget(etiqueta(
            "Usa el escáner conectado vía WIA.\n"
            f"Resolución: {WIAScanWorker.DPI_SCAN} DPI color (PNG sin pérdida).\n"
            "Abre el diálogo de 'Nueva digitalización'.",
            rol="hint", wrap=True,
        ))
        lay.addStretch()

        self.btn_digitalizar = boton("Digitalizar", height=SIZE["btn_lg"],
                                     on_click=self._on_digitalizar)
        lay.addWidget(self.btn_digitalizar)

        self.lbl_wia_estado = etiqueta("", rol="hint",
                                       align=Qt.AlignmentFlag.AlignCenter)
        self.lbl_wia_estado.hide()
        lay.addWidget(self.lbl_wia_estado)
        return panel

    def _panel_manual(self) -> QFrame:
        panel, lay = tarjeta(padding=SPACE["lg"], spacing=SPACE["sm"])
        lay.addWidget(etiqueta("Cargar imagen manualmente", rol="subtitulo"))
        lay.addWidget(etiqueta(
            "Arrastrá una imagen a la zona de abajo, o examiná tus carpetas.",
            rol="hint", wrap=True,
        ))

        self.zona_drop = ZonaDrop()
        self.zona_drop.imagen_soltada.connect(self._on_imagen_recibida)
        lay.addWidget(self.zona_drop, 1)

        lay.addWidget(boton("Examinar archivos…", variant="secondary",
                            on_click=self._on_examinar))
        return panel

    def _panel_preview(self) -> QFrame:
        self.panel_preview, lay_v = tarjeta(acento=True, padding=SPACE["md"])
        fila = QHBoxLayout()
        fila.setSpacing(SPACE["md"])

        self.lbl_prev_img = QLabel()
        self.lbl_prev_img.setObjectName("lienzoPagina")
        self.lbl_prev_img.setFixedSize(84, 110)
        self.lbl_prev_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fila.addWidget(self.lbl_prev_img)

        info = QVBoxLayout()
        info.setSpacing(2)
        self.lbl_prev_nombre = etiqueta("—", rol="subtitulo")
        info.addWidget(self.lbl_prev_nombre)
        self.lbl_prev_ruta = etiqueta("", rol="hint", wrap=True)
        info.addWidget(self.lbl_prev_ruta)
        info.addStretch()
        fila.addLayout(info, 1)

        self.btn_cambiar = boton("Cambiar imagen", variant="ghost",
                                 height=SIZE["btn_sm"],
                                 on_click=self._on_cambiar_imagen)
        fila.addWidget(self.btn_cambiar, 0, Qt.AlignmentFlag.AlignTop)

        lay_v.addLayout(fila)
        self.panel_preview.hide()
        return self.panel_preview

    # ── Lógica WIA ─────────────────────────────────────────────────────
    def _on_digitalizar(self):
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            QMessageBox.warning(
                self, "Dependencia faltante",
                "pywin32 no está instalado.\n\nEjecutá:\n"
                "  pip install pywin32\n\nLuego reiniciá la aplicación.",
            )
            return

        self.btn_digitalizar.setEnabled(False)
        self.btn_digitalizar.setText("Escaneando…")
        self.lbl_wia_estado.setText("Abriendo diálogo WIA…")
        self.lbl_wia_estado.show()

        worker = WIAScanWorker()
        self._worker = worker
        _WORKERS_VIVOS.add(worker)
        worker.finished.connect(lambda: _WORKERS_VIVOS.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.scan_completado.connect(self._on_scan_completado)
        worker.scan_cancelado.connect(self._restablecer_btn_wia)
        worker.scan_error.connect(self._on_wia_error)
        worker.start()

    def _on_scan_completado(self, ruta: str):
        self._temporales.append(ruta)
        self._on_imagen_recibida(ruta)

    def _restablecer_btn_wia(self):
        self.btn_digitalizar.setEnabled(True)
        self.btn_digitalizar.setText("Digitalizar")
        self.lbl_wia_estado.hide()

    def _on_wia_error(self, msg: str):
        self._restablecer_btn_wia()
        QMessageBox.warning(
            self, "Error al digitalizar",
            f"El escáner reportó un error:\n\n{msg}\n\n"
            "Verificá que el escáner esté conectado y encendido.",
        )

    # ── Lógica manual ───────────────────────────────────────────────────
    def _on_examinar(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar imagen escaneada", os.path.expanduser("~"),
            "Imágenes (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp)",
        )
        if ruta:
            self._on_imagen_recibida(ruta)

    # ── Imagen recibida (cualquier fuente) ──────────────────────────────
    def _on_imagen_recibida(self, ruta: str):
        if not ruta or not Path(ruta).exists():
            QMessageBox.warning(self, "Imagen no encontrada",
                                f"No se pudo leer:\n{ruta}")
            return

        pm = QPixmap(ruta)
        if pm.isNull():
            QMessageBox.warning(
                self, "Formato no soportado",
                f"No se pudo interpretar la imagen:\n{os.path.basename(ruta)}",
            )
            return

        self._ruta_img = ruta
        self._restablecer_btn_wia()
        self.lbl_prev_img.setPixmap(pm.scaled(
            self.lbl_prev_img.width(), self.lbl_prev_img.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

        nombre = os.path.basename(ruta)
        self.lbl_prev_nombre.setText(nombre)
        self.lbl_prev_ruta.setText(ruta)
        self.panel_preview.show()
        self.btn_usar.setEnabled(True)
        self.btn_usar.setFocus()
        self.pie.set_estado(f"✔  Lista: {nombre}", rol="ok")

    def _on_cambiar_imagen(self):
        self._ruta_img = None
        self._imagen_entregada = False
        self.lbl_prev_img.clear()
        self.panel_preview.hide()
        self.btn_usar.setEnabled(False)
        self.pie.set_estado("Esperando imagen…")

    def _on_usar_imagen(self):
        if self._ruta_img:
            self._imagen_entregada = True
            self.imagen_lista.emit(self._ruta_img)

    # ── Varios ──────────────────────────────────────────────────────────
    def _on_tema_cambiado(self, _modo: str):
        if self._ruta_img:
            self._on_imagen_recibida(self._ruta_img)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelar.emit()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) \
                and self.btn_usar.isEnabled():
            self._on_usar_imagen()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        # No esperamos al worker: el diálogo WIA es modal del sistema y
        # bloquearía la app entera. El thread se limpia solo (_WORKERS_VIVOS).
        try:
            theme_signals.changed.disconnect(self._on_tema_cambiado)
        except (TypeError, RuntimeError):
            pass
        if not self._imagen_entregada:
            for f in self._temporales:
                try:
                    os.remove(f)
                except OSError:
                    pass
        super().closeEvent(event)
