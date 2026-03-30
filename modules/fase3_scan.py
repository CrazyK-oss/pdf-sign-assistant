# modules/fase3_scan.py
# Fase 3: Stand-by post-impresión.
# Digitalización directa via WIA (Windows Image Acquisition) + carga manual.


import os
import glob
import uuid
import tempfile
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QSpacerItem, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QFont, QDragEnterEvent, QDropEvent



# ─────────────────────────────────────────────────────────────────────────
#  Worker: Lanza el diálogo WIA en hilo aparte para no bloquear la UI
# ─────────────────────────────────────────────────────────────────────────
class WIAScanWorker(QThread):
    scan_completado = pyqtSignal(str)   # ruta del archivo guardado
    scan_cancelado  = pyqtSignal()
    scan_error      = pyqtSignal(str)


    def run(self):
        try:
            import win32com.client

            # Limpiar escaneos temporales anteriores para evitar
            # el error WIA "Este archivo ya existe" en el segundo escaneo
            for f in glob.glob(
                os.path.join(tempfile.gettempdir(), "pdf_sign_scan_*.png")
            ):
                try:
                    os.remove(f)
                except Exception:
                    pass

            # WIA.CommonDialog — el mismo motor que "Fax y Escáner de Windows"
            wia = win32com.client.Dispatch("WIA.CommonDialog")

            # ShowAcquireImage(
            #   DeviceType:          1 = Scanner
            #   Intent:              1 = Color
            #   Bias:                4 = MaximumQuality
            #   FormatID:            PNG = {B96B3CAF-0728-11D3-9D7B-0000F81EF32E}
            #   AlwaysSelectDevice:  False (usa el escáner por defecto)
            #   UseCommonUI:         True  (muestra el diálogo completo de WIA)
            #   CancelError:         True  (lanza excepción si el usuario cancela)
            # )
            img_wia = wia.ShowAcquireImage(
                1,
                1,
                4,
                "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}",
                False,
                True,
                True
            )

            # Nombre único por escaneo → WIA nunca choca con un archivo previo
            nombre = f"pdf_sign_scan_{uuid.uuid4().hex[:8]}.png"
            ruta_destino = os.path.join(tempfile.gettempdir(), nombre)
            img_wia.SaveFile(ruta_destino)
            self.scan_completado.emit(ruta_destino)

        except Exception as e:
            msg = str(e).lower()
            # Códigos/textos de cancelación WIA
            if any(x in msg for x in ["cancel", "0x80210003", "user cancel"]):
                self.scan_cancelado.emit()
            else:
                self.scan_error.emit(str(e))



# ─────────────────────────────────────────────────────────────────────────
#  Zona de drag & drop
#  NOTA: el clic para abrir el explorador lo maneja el botón "Examinar"
#  externo — ZonaDrop NO implementa mousePressEvent para evitar que se
#  duplique el QFileDialog cuando el usuario hace clic en el botón.
# ─────────────────────────────────────────────────────────────────────────
class ZonaDrop(QFrame):
    imagen_soltada = pyqtSignal(str)


    _ESTILO_BASE = """
        ZonaDrop {{
            background: {bg};
            border: 2px dashed {border};
            border-radius: 10px;
        }}
    """


    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self._set_estado_normal()


        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(6)


        self.lbl_icono = QLabel("⬇")
        self.lbl_icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icono.setStyleSheet(
            "font-size: 26px; color: #bab9b4; border: none; background: transparent;"
        )
        lay.addWidget(self.lbl_icono)


        lbl_txt = QLabel("Arrastra una imagen aquí")
        lbl_txt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_txt.setStyleSheet(
            "color: #7a7974; font-size: 12px; border: none; background: transparent;"
        )
        lay.addWidget(lbl_txt)


    def _set_estado_normal(self):
        self.setStyleSheet(
            self._ESTILO_BASE.format(bg="#f3f0ec", border="rgba(40,37,29,0.18)")
        )


    def _set_estado_hover(self):
        self.setStyleSheet(
            self._ESTILO_BASE.format(bg="#e4f2f1", border="#01696f")
        )


    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            url = e.mimeData().urls()[0].toLocalFile()
            if url.lower().endswith(
                (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp")
            ):
                e.acceptProposedAction()
                self._set_estado_hover()
                return
        e.ignore()


    def dragLeaveEvent(self, e):
        self._set_estado_normal()


    def dropEvent(self, e: QDropEvent):
        self._set_estado_normal()
        if e.mimeData().hasUrls():
            ruta = e.mimeData().urls()[0].toLocalFile()
            self.imagen_soltada.emit(ruta)



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
        self.ruta_pdf    = ruta_pdf
        self.num_pagina  = num_pagina
        self._ruta_img   = None
        self._worker     = None
        self._construir_ui()


    # ── Construcción de la UI ──────────────────────────────────────────
    def _construir_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)


        # ── Cabecera ────────────────────────────────────────────────────
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


        nombre = os.path.basename(self.ruta_pdf)
        lbl_titulo = QLabel(
            f"Escanear  ·  Página {self.num_pagina + 1}  ·  {nombre}"
        )
        font_cab = QFont("Segoe UI", 13)
        font_cab.setWeight(QFont.Weight.Medium)
        lbl_titulo.setFont(font_cab)
        lbl_titulo.setStyleSheet("color: #28251d;")
        lay_cab.addWidget(lbl_titulo)


        lay_cab.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )


        btn_volver = QPushButton("← Volver a páginas")
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
        lay_cab.addWidget(btn_volver)
        raiz.addWidget(cab)


        # ── Contenido central ────────────────────────────────────────────
        cuerpo = QWidget()
        cuerpo.setStyleSheet("background: #f7f6f2;")
        lay_cuerpo = QVBoxLayout(cuerpo)
        lay_cuerpo.setContentsMargins(40, 28, 40, 28)
        lay_cuerpo.setSpacing(20)


        lbl_desc = QLabel(
            f"La página {self.num_pagina + 1} fue enviada a la impresora. "
            "Cuando tengas la hoja firmada, escanéala con el botón de abajo "
            "o carga la imagen manualmente."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #7a7974; font-size: 13px;")
        lay_cuerpo.addWidget(lbl_desc)


        # ── Fila: dos paneles de opciones ────────────────────────────────
        fila = QHBoxLayout()
        fila.setSpacing(16)
        fila.addWidget(self._panel_wia())
        fila.addWidget(self._separador_o())
        fila.addWidget(self._panel_manual())
        lay_cuerpo.addLayout(fila)


        # ── Panel de preview (oculto hasta tener imagen) ─────────────────
        lay_cuerpo.addWidget(self._panel_preview())


        raiz.addWidget(cuerpo, 1)
        raiz.addWidget(self._barra_inferior())


    def _panel_wia(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background: #f9f8f5;
                border: 1px solid rgba(40,37,29,0.10);
                border-radius: 10px;
            }
        """)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)


        font_h = QFont("Segoe UI", 12)
        font_h.setWeight(QFont.Weight.Medium)


        t = QLabel("Digitalizar con el escáner")
        t.setFont(font_h)
        t.setStyleSheet("color: #28251d;")
        lay.addWidget(t)


        d = QLabel(
            "Usa el escáner conectado vía WIA.\n"
            "Abre el mismo diálogo que «Nueva digitalización»\n"
            "en Fax y Escáner de Windows."
        )
        d.setWordWrap(True)
        d.setStyleSheet("color: #7a7974; font-size: 12px;")
        lay.addWidget(d)


        lay.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )


        self.btn_digitalizar = QPushButton("Digitalizar")
        self.btn_digitalizar.setFixedHeight(42)
        self.btn_digitalizar.setStyleSheet("""
            QPushButton {
                background: #01696f;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 700;
                letter-spacing: 0.3px;
            }
            QPushButton:hover   { background: #0c4e54; }
            QPushButton:pressed { background: #0f3638; }
            QPushButton:disabled { background: #dcd9d5; color: #bab9b4; }
        """)
        self.btn_digitalizar.clicked.connect(self._on_digitalizar)
        lay.addWidget(self.btn_digitalizar)


        self.lbl_wia_estado = QLabel("")
        self.lbl_wia_estado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_wia_estado.setStyleSheet("color: #7a7974; font-size: 11px;")
        self.lbl_wia_estado.hide()
        lay.addWidget(self.lbl_wia_estado)


        return panel


    def _separador_o(self) -> QLabel:
        lbl = QLabel("o")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFixedWidth(28)
        lbl.setStyleSheet("color: #bab9b4; font-size: 13px;")
        return lbl


    def _panel_manual(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background: #f9f8f5;
                border: 1px solid rgba(40,37,29,0.10);
                border-radius: 10px;
            }
        """)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)


        font_h = QFont("Segoe UI", 12)
        font_h.setWeight(QFont.Weight.Medium)


        t = QLabel("Cargar imagen manualmente")
        t.setFont(font_h)
        t.setStyleSheet("color: #28251d;")
        lay.addWidget(t)


        d = QLabel("Arrastra una imagen a la zona de abajo,\no examina tus carpetas.")
        d.setWordWrap(True)
        d.setStyleSheet("color: #7a7974; font-size: 12px;")
        lay.addWidget(d)


        self.zona_drop = ZonaDrop()
        self.zona_drop.imagen_soltada.connect(self._on_imagen_recibida)
        lay.addWidget(self.zona_drop)


        btn_examinar = QPushButton("Examinar archivos…")
        btn_examinar.setFixedHeight(36)
        btn_examinar.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #01696f;
                border: 1px solid rgba(1,105,111,0.50);
                border-radius: 6px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #01696f;
                color: white;
                border-color: #01696f;
            }
        """)
        btn_examinar.clicked.connect(self._on_examinar)
        lay.addWidget(btn_examinar)


        return panel


    def _panel_preview(self) -> QFrame:
        self.panel_preview = QFrame()
        self.panel_preview.setStyleSheet("""
            QFrame {
                background: #f9f8f5;
                border: 1px solid rgba(1,105,111,0.30);
                border-radius: 10px;
            }
        """)
        lay = QHBoxLayout(self.panel_preview)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(16)


        self.lbl_prev_img = QLabel()
        self.lbl_prev_img.setFixedSize(90, 118)
        self.lbl_prev_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_prev_img.setStyleSheet(
            "background: #edeae5; border-radius: 4px;"
        )
        lay.addWidget(self.lbl_prev_img)


        info = QVBoxLayout()
        self.lbl_prev_nombre = QLabel("—")
        font_n = QFont("Segoe UI", 12)
        font_n.setWeight(QFont.Weight.Medium)
        self.lbl_prev_nombre.setFont(font_n)
        self.lbl_prev_nombre.setStyleSheet("color: #28251d;")
        info.addWidget(self.lbl_prev_nombre)


        self.lbl_prev_ruta = QLabel("")
        self.lbl_prev_ruta.setStyleSheet("color: #7a7974; font-size: 11px;")
        self.lbl_prev_ruta.setWordWrap(True)
        info.addWidget(self.lbl_prev_ruta)


        info.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )
        lay.addLayout(info)
        lay.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )


        btn_cambiar = QPushButton("Cambiar imagen")
        btn_cambiar.setFixedHeight(32)
        btn_cambiar.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #7a7974;
                border: 1px solid rgba(40,37,29,0.20);
                border-radius: 5px;
                padding: 0 12px;
                font-size: 12px;
            }
            QPushButton:hover { color: #28251d; border-color: rgba(40,37,29,0.45); }
        """)
        btn_cambiar.clicked.connect(self._on_cambiar_imagen)
        lay.addWidget(btn_cambiar)


        self.panel_preview.hide()
        return self.panel_preview


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


        self.lbl_estado_inf = QLabel("Esperando imagen…")
        self.lbl_estado_inf.setStyleSheet("color: #7a7974; font-size: 13px;")
        lay.addWidget(self.lbl_estado_inf)


        lay.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )


        self.btn_usar = QPushButton("Usar esta imagen  →")
        self.btn_usar.setFixedHeight(40)
        self.btn_usar.setEnabled(False)
        self.btn_usar.setStyleSheet("""
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
        self.btn_usar.clicked.connect(self._on_usar_imagen)
        lay.addWidget(self.btn_usar)


        return barra


    # ── Lógica WIA ─────────────────────────────────────────────────────
    def _on_digitalizar(self):
        try:
            import win32com.client  # noqa: F401 — solo verificar disponibilidad
        except ImportError:
            QMessageBox.warning(
                self, "Dependencia faltante",
                "pywin32 no está instalado.\n\nEjecuta en tu terminal:\n"
                "  pip install pywin32\n\nLuego reinicia la aplicación."
            )
            return


        self.btn_digitalizar.setEnabled(False)
        self.btn_digitalizar.setText("Escaneando…")
        self.lbl_wia_estado.setText("Abriendo diálogo WIA…")
        self.lbl_wia_estado.show()


        self._worker = WIAScanWorker()
        self._worker.scan_completado.connect(self._on_imagen_recibida)
        self._worker.scan_cancelado.connect(self._restablecer_btn_wia)
        self._worker.scan_error.connect(self._on_wia_error)
        self._worker.start()


    def _restablecer_btn_wia(self):
        self.btn_digitalizar.setEnabled(True)
        self.btn_digitalizar.setText("Digitalizar")
        self.lbl_wia_estado.hide()


    def _on_wia_error(self, msg: str):
        self._restablecer_btn_wia()
        QMessageBox.warning(
            self, "Error al digitalizar",
            f"El escáner reportó un error:\n\n{msg}\n\n"
            "Verifica que el escáner esté conectado y encendido."
        )


    # ── Lógica manual ───────────────────────────────────────────────────
    def _on_examinar(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar imagen escaneada",
            os.path.expanduser("~"),
            "Imágenes (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp)"
        )
        if ruta:
            self._on_imagen_recibida(ruta)


    # ── Imagen recibida (cualquier fuente) ──────────────────────────────
    def _on_imagen_recibida(self, ruta: str):
        self._ruta_img = ruta
        self._restablecer_btn_wia()


        # Preview
        pm = QPixmap(ruta)
        if not pm.isNull():
            self.lbl_prev_img.setPixmap(
                pm.scaled(
                    90, 118,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            )


        nombre = os.path.basename(ruta)
        self.lbl_prev_nombre.setText(nombre)
        self.lbl_prev_ruta.setText(ruta)
        self.panel_preview.show()


        self.btn_usar.setEnabled(True)
        self.lbl_estado_inf.setText(f"Lista: {nombre}")
        self.lbl_estado_inf.setStyleSheet(
            "color: #01696f; font-size: 13px; font-weight: 600;"
        )


    def _on_cambiar_imagen(self):
        self._ruta_img = None
        self.lbl_prev_img.clear()   # limpiar pixmap anterior
        self.panel_preview.hide()
        self.btn_usar.setEnabled(False)
        self.lbl_estado_inf.setText("Esperando imagen…")
        self.lbl_estado_inf.setStyleSheet("color: #7a7974; font-size: 13px;")


    def _on_usar_imagen(self):
        if self._ruta_img:
            self.imagen_lista.emit(self._ruta_img)


    def closeEvent(self, event):
        # Limpiar archivos temporales de escaneos anteriores al cerrar
        for f in glob.glob(
            os.path.join(tempfile.gettempdir(), "pdf_sign_scan_*.png")
        ):
            try:
                os.remove(f)
            except Exception:
                pass
        if self._worker and self._worker.isRunning():
            self._worker.wait()
        super().closeEvent(event)