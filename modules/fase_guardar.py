import os
import sys
import glob          # ✅ FIX: para limpiar archivos temporales anteriores
import uuid          # ✅ FIX: para generar nombres únicos
import tempfile
import comtypes
import comtypes.client
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMimeData
from PyQt6.QtGui import QPixmap, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QFileDialog, QMessageBox, QFrame, QApplication
)


# ─────────────────────────────────────────────
#  Worker WIA (hilo secundario)
# ─────────────────────────────────────────────
class WIAScanWorker(QThread):
    scan_completado  = pyqtSignal(str)   # ruta del archivo escaneado
    scan_cancelado   = pyqtSignal()
    scan_error       = pyqtSignal(str)

    def __init__(self, ruta_salida: str, parent=None):
        super().__init__(parent)
        self._ruta_salida = ruta_salida

    def run(self):
        try:
            wia = comtypes.client.CreateObject("WIA.CommonDialog")
            device = wia.ShowSelectDevice(0, True)
            if device is None:
                self.scan_cancelado.emit()
                return

            imagen = wia.ShowAcquireImage(
                0,       # WiaDeviceType: unspecified
                0,       # WiaImageIntent
                0,       # WiaImageBias
                "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}",  # BMP
                True,
                True,
                False
            )
            if imagen is None:
                self.scan_cancelado.emit()
                return

            imagen.SaveFile(self._ruta_salida)
            self.scan_completado.emit(self._ruta_salida)

        except Exception as e:
            codigo = getattr(e, 'hresult', 0)
            # 0x80210003 = usuario canceló en el diálogo WIA
            if codigo == -2147024893 or codigo == 0x80210003:
                self.scan_cancelado.emit()
            else:
                self.scan_error.emit(str(e))


# ─────────────────────────────────────────────
#  Zona de drag & drop
# ─────────────────────────────────────────────
class ZonaDrop(QFrame):
    archivo_soltado = pyqtSignal(str)

    EXTENSIONES_VALIDAS = {".bmp", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("ZonaDrop")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._lbl_icono = QLabel("📂", self)
        self._lbl_icono.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._lbl_texto = QLabel("Arrastra una imagen aquí\no haz clic en Examinar", self)
        self._lbl_texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_texto.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._lbl_icono)
        lay.addWidget(self._lbl_texto)

    # ── drag & drop ──────────────────────────
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and self._es_valida(urls[0].toLocalFile()):
                event.acceptProposedAction()
                self.setProperty("drag_over", True)
                self.style().unpolish(self)
                self.style().polish(self)
                return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("drag_over", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("drag_over", False)
        self.style().unpolish(self)
        self.style().polish(self)
        ruta = event.mimeData().urls()[0].toLocalFile()
        if self._es_valida(ruta):
            self.archivo_soltado.emit(ruta)

    def _es_valida(self, ruta: str) -> bool:
        ext = os.path.splitext(ruta)[1].lower()
        return ext in self.EXTENSIONES_VALIDAS


# ─────────────────────────────────────────────
#  Pantalla principal de escaneo
# ─────────────────────────────────────────────
class FaseEscaneo(QWidget):
    escaneo_listo = pyqtSignal(str)   # emite ruta de imagen al terminar

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Digitalizar página")
        self.resize(560, 480)

        self._ruta_img: str | None = None
        self._worker: WIAScanWorker | None = None

        self._construir_ui()

    # ── UI ───────────────────────────────────
    def _construir_ui(self):
        lay_principal = QVBoxLayout(self)
        lay_principal.setContentsMargins(20, 20, 20, 20)
        lay_principal.setSpacing(14)

        # Título
        lbl_titulo = QLabel("Escanear página firmada")
        lbl_titulo.setObjectName("titulo")
        lay_principal.addWidget(lbl_titulo)

        # ── Panel WIA ────────────────────────
        grp_wia = QFrame()
        grp_wia.setObjectName("panel_seccion")
        lay_wia = QVBoxLayout(grp_wia)
        lay_wia.setSpacing(8)

        lbl_wia = QLabel("Usar escáner (WIA):")
        lbl_wia.setObjectName("subtitulo")
        lay_wia.addWidget(lbl_wia)

        self.btn_wia = QPushButton("▶  Iniciar escaneo")
        self.btn_wia.setObjectName("btn_primario")
        self.btn_wia.clicked.connect(self._on_iniciar_wia)
        lay_wia.addWidget(self.btn_wia)

        self.lbl_estado_wia = QLabel("")
        self.lbl_estado_wia.setObjectName("lbl_estado")
        lay_wia.addWidget(self.lbl_estado_wia)

        lay_principal.addWidget(grp_wia)

        # ── Panel manual ─────────────────────
        grp_manual = QFrame()
        grp_manual.setObjectName("panel_seccion")
        lay_manual = QVBoxLayout(grp_manual)
        lay_manual.setSpacing(8)

        lbl_manual = QLabel("O carga una imagen manualmente:")
        lbl_manual.setObjectName("subtitulo")
        lay_manual.addWidget(lbl_manual)

        self.zona_drop = ZonaDrop()
        self.zona_drop.setMinimumHeight(100)
        self.zona_drop.archivo_soltado.connect(self._on_imagen_cargada)
        lay_manual.addWidget(self.zona_drop)

        self.btn_examinar = QPushButton("Examinar…")
        self.btn_examinar.clicked.connect(self._on_examinar)
        lay_manual.addWidget(self.btn_examinar)

        lay_principal.addWidget(grp_manual)

        # ── Preview ──────────────────────────
        self.panel_preview = QFrame()
        self.panel_preview.setObjectName("panel_preview")
        lay_prev = QHBoxLayout(self.panel_preview)

        self.lbl_prev_img = QLabel()
        self.lbl_prev_img.setFixedSize(90, 118)
        self.lbl_prev_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_prev_img.setObjectName("miniatura_previa")
        lay_prev.addWidget(self.lbl_prev_img)

        lay_info = QVBoxLayout()
        self.lbl_prev_nombre = QLabel("")
        self.lbl_prev_nombre.setWordWrap(True)
        lay_info.addWidget(self.lbl_prev_nombre)

        btn_cambiar = QPushButton("Cambiar imagen")
        btn_cambiar.clicked.connect(self._on_cambiar_imagen)
        lay_info.addWidget(btn_cambiar)
        lay_prev.addLayout(lay_info)

        self.panel_preview.hide()
        lay_principal.addWidget(self.panel_preview)

        lay_principal.addStretch()

        # ── Botones finales ───────────────────
        lay_btns = QHBoxLayout()
        lay_btns.addStretch()

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.close)
        lay_btns.addWidget(btn_cancelar)

        self.btn_continuar = QPushButton("Continuar →")
        self.btn_continuar.setObjectName("btn_primario")
        self.btn_continuar.setEnabled(False)
        self.btn_continuar.clicked.connect(self._on_continuar)
        lay_btns.addWidget(self.btn_continuar)

        lay_principal.addLayout(lay_btns)

    # ── Lógica WIA ───────────────────────────
    def _on_iniciar_wia(self):
        self.btn_wia.setEnabled(False)
        self.lbl_estado_wia.setText("Escaneando…")

        # ✅ FIX: nombre único por cada escaneo → WIA nunca choca con archivo existente
        nombre_tmp = f"wia_scan_{uuid.uuid4().hex[:8]}.bmp"
        ruta_tmp = os.path.join(tempfile.gettempdir(), nombre_tmp)

        self._worker = WIAScanWorker(ruta_tmp)
        self._worker.scan_completado.connect(self._on_imagen_cargada)
        self._worker.scan_cancelado.connect(self._on_wia_cancelado)
        self._worker.scan_error.connect(self._on_wia_error)
        self._worker.start()

    def _on_wia_cancelado(self):
        self.lbl_estado_wia.setText("Escaneo cancelado.")
        self._restablecer_btn_wia()

    def _on_wia_error(self, mensaje: str):
        self._restablecer_btn_wia()
        self.lbl_estado_wia.setText("")
        QMessageBox.critical(
            self,
            "Error al digitalizar",
            f"El escáner reportó un error:\n\n{mensaje}\n\n"
            "Verifica que el escáner esté conectado y encendido."
        )

    def _restablecer_btn_wia(self):
        self.btn_wia.setEnabled(True)

    # ── Lógica carga manual ───────────────────
    def _on_examinar(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar imagen escaneada",
            "",
            "Imágenes (*.bmp *.png *.jpg *.jpeg *.tif *.tiff)"
        )
        if ruta:
            self._on_imagen_cargada(ruta)

    def _on_cambiar_imagen(self):
        self._ruta_img = None
        self.lbl_prev_img.clear()    # ✅ FIX: limpiar pixmap anterior
        self.panel_preview.hide()
        self.btn_continuar.setEnabled(False)

    # ── Imagen cargada (desde cualquier fuente) ──
    def _on_imagen_cargada(self, ruta: str):
        self.lbl_estado_wia.setText("✔ Imagen lista.")
        self._ruta_img = ruta

        pix = QPixmap(ruta)
        if not pix.isNull():
            self.lbl_prev_img.setPixmap(
                pix.scaled(
                    self.lbl_prev_img.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            )

        self.lbl_prev_nombre.setText(os.path.basename(ruta))
        self.panel_preview.show()
        self.btn_continuar.setEnabled(True)
        self._restablecer_btn_wia()

    # ── Continuar ─────────────────────────────
    def _on_continuar(self):
        if self._ruta_img:
            self.escaneo_listo.emit(self._ruta_img)
            self.close()

    # ── Cierre: limpiar archivos temporales ──
    def closeEvent(self, event):
        # Esperar worker si está corriendo
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(3000)

        # ✅ FIX: eliminar todos los archivos temporales de escaneos anteriores
        patron = os.path.join(tempfile.gettempdir(), "wia_scan_*.bmp")
        for f in glob.glob(patron):
            try:
                os.remove(f)
            except Exception:
                pass

        super().closeEvent(event)