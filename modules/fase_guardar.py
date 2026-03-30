"""
modules/fase_guardar.py
=======================
Fase 4 del flujo principal: confirmación y guardado del PDF modificado.

Recibe:
  - ruta_pdf    : Path del PDF de trabajo (en pdfs_trabajo/)
  - ruta_imagen : str  ruta de la imagen resultante (PNG/BMP/JPG)
  - num_pagina  : int  índice 0-based de la página a reemplazar

Emite:
  - guardado_listo(Path)  → ruta del PDF final guardado en pdfs_firmados/
  - cancelado()           → el usuario descartó la operación

Correcciones críticas (v8)
---------------------------
* BUGFIX PRINCIPAL (v8): img2pdf puede crashear el proceso a nivel de extensión
  C (pikepdf/libjpeg/etc.) incluso dentro de un try/except — Python nunca llega
  a atrapar la excepción porque el crash ocurre por debajo del intérprete.
  Solución: img2pdf se ejecuta en un SUBPROCESO SEPARADO con subprocess.run().
  Si el subproceso muere (returncode != 0, timeout, o cualquier excepción), el
  proceso principal NO se ve afectado y cae automáticamente al fallback Pillow.

* Conservado de v7: Pillow como motor principal de fallback, normalización de
  modo de color, logging granular, guard anti-doble-disparo, worker sin parent=,
  señal interna _despachar_guardado_listo con QueuedConnection, closeEvent.
"""

import logging
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QMessageBox, QSizePolicy, QSpacerItem,
    QProgressBar,
)

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)


# ─────────────────────────────────────────────────────────────────────────
#  Script auxiliar que corre img2pdf en subproceso aislado
# ─────────────────────────────────────────────────────────────────────────

# Código Python inline que se ejecuta en el subproceso hijo.
# Recibe la ruta de la imagen por argv[1] y escribe el PDF en argv[2].
_IMG2PDF_WORKER_SCRIPT = """
import sys, img2pdf
ruta_img = sys.argv[1]
ruta_out  = sys.argv[2]
with open(ruta_img, "rb") as f:
    datos = img2pdf.convert(f)
with open(ruta_out, "wb") as f:
    f.write(datos)
"""


# ─────────────────────────────────────────────────────────────────────────
#  Helpers de conversión imagen → PDF temporal
# ─────────────────────────────────────────────────────────────────────────

def _normalizar_modo_pillow(img):
    """Convierte la imagen al modo correcto para guardar como PDF con Pillow.

    Pillow soporta RGB y L en PDF. Cualquier otro modo se convierte:
      - RGBA / PA  → composición sobre fondo blanco → RGB
      - P (paleta) → RGB
      - L, LA      → L (escala de grises, alpha descartada)
      - CMYK y resto → RGB
    """
    modo = img.mode
    log.debug("_normalizar_modo_pillow — modo original: %s", modo)
    if modo == "RGB":
        return img
    if modo == "L":
        return img
    if modo in ("RGBA", "PA"):
        from PIL import Image as _Image
        fondo = _Image.new("RGB", img.size, (255, 255, 255))
        alpha = img.convert("RGBA").split()[3]
        fondo.paste(img.convert("RGBA"), mask=alpha)
        log.debug("_normalizar_modo_pillow — RGBA/PA → RGB con fondo blanco")
        return fondo
    if modo in ("LA",):
        img_l = img.convert("L")
        log.debug("_normalizar_modo_pillow — LA → L")
        return img_l
    # P, CMYK, YCbCr, LAB, HSV, I, F, …
    img_rgb = img.convert("RGB")
    log.debug("_normalizar_modo_pillow — %s → RGB", modo)
    return img_rgb


def _imagen_a_pdf_pillow(ruta_imagen: str) -> str:
    """Convierte una imagen a PDF de una página usando Pillow.

    Devuelve la ruta del archivo temporal. Lanza excepción si falla.
    """
    from PIL import Image
    log.debug("Pillow: abriendo imagen %s", ruta_imagen)
    img = Image.open(ruta_imagen)
    log.debug("Pillow: imagen abierta — modo=%s tamaño=%s formato=%s",
              img.mode, img.size, img.format)
    img = _normalizar_modo_pillow(img)
    log.debug("Pillow: modo normalizado → %s", img.mode)
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    log.debug("Pillow: guardando PDF en %s", tmp.name)
    img.save(tmp.name, "PDF", resolution=150)
    log.debug("Pillow: PDF guardado OK — tamaño=%d bytes",
              Path(tmp.name).stat().st_size)
    return tmp.name


def _imagen_a_pdf_img2pdf(ruta_imagen: str) -> str:
    """Intenta convertir la imagen a PDF usando img2pdf en un subproceso aislado.

    Si img2pdf crashea a nivel nativo (extensión C), el crash ocurre en el
    subproceso hijo — el proceso principal sobrevive y este método lanza
    RuntimeError para que el llamador use Pillow como fallback.

    Devuelve la ruta del PDF temporal. Lanza excepción si falla por cualquier
    motivo (ImportError, crash nativo, timeout, error de escritura…).
    """
    # Verificar que img2pdf está instalado antes de lanzar el subproceso.
    try:
        import importlib
        importlib.import_module("img2pdf")
    except ImportError as exc:
        raise ImportError("img2pdf no está instalado") from exc

    tmp_out = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_out.close()

    log.debug("img2pdf (subprocess): lanzando subproceso para %s → %s",
              ruta_imagen, tmp_out.name)
    try:
        resultado = subprocess.run(
            [sys.executable, "-c", _IMG2PDF_WORKER_SCRIPT,
             ruta_imagen, tmp_out.name],
            capture_output=True,
            timeout=60,          # máximo 60 s para la conversión
        )
    except subprocess.TimeoutExpired as exc:
        _borrar_si_existe(tmp_out.name)
        raise RuntimeError("img2pdf: timeout tras 60 s") from exc
    except Exception as exc:
        _borrar_si_existe(tmp_out.name)
        raise RuntimeError(f"img2pdf: error al lanzar subproceso — {exc}") from exc

    if resultado.returncode != 0:
        stderr = resultado.stderr.decode(errors="replace").strip()
        stdout = resultado.stdout.decode(errors="replace").strip()
        _borrar_si_existe(tmp_out.name)
        raise RuntimeError(
            f"img2pdf subproceso terminó con código {resultado.returncode}.\n"
            f"stderr: {stderr}\nstdout: {stdout}"
        )

    tamaño = Path(tmp_out.name).stat().st_size
    if tamaño == 0:
        _borrar_si_existe(tmp_out.name)
        raise RuntimeError("img2pdf generó un PDF vacío (0 bytes)")

    log.debug("img2pdf (subprocess): OK — %d bytes → %s", tamaño, tmp_out.name)
    return tmp_out.name


def _borrar_si_existe(ruta: str) -> None:
    try:
        if ruta and Path(ruta).exists():
            os.remove(ruta)
    except Exception:
        pass


def _convertir_imagen_a_pdf(ruta_imagen: str) -> str:
    """Motor principal de conversión imagen → PDF de una página.

    Estrategia (v8):
      1. Intentar img2pdf en subproceso aislado — más fiel (sin recompresión
         JPEG). Si el subproceso crashea, el proceso principal sobrevive y se
         registra como WARNING.
      2. Pillow — robusto, soporta todos los formatos y modos de color.

    Devuelve la ruta del PDF temporal. Lanza excepción si ambos fallan.
    """
    # ── Intento 1: img2pdf (subproceso aislado) ──────────────────────
    try:
        ruta = _imagen_a_pdf_img2pdf(ruta_imagen)
        log.debug("_convertir_imagen_a_pdf: img2pdf (subprocess) exitoso → %s", ruta)
        return ruta
    except ImportError:
        log.debug("_convertir_imagen_a_pdf: img2pdf no instalado, usando Pillow")
    except Exception as e_i2p:
        log.warning(
            "_convertir_imagen_a_pdf: img2pdf falló (%s: %s) — usando Pillow como fallback",
            type(e_i2p).__name__, e_i2p,
        )

    # ── Intento 2: Pillow (motor de fallback robusto) ────────────────
    log.debug("_convertir_imagen_a_pdf: ejecutando conversión con Pillow")
    ruta = _imagen_a_pdf_pillow(ruta_imagen)
    log.debug("_convertir_imagen_a_pdf: Pillow exitoso → %s", ruta)
    return ruta


# ─────────────────────────────────────────────────────────────────────────
#  Worker: convierte imagen → página PDF y reemplaza en hilo secundario
# ─────────────────────────────────────────────────────────────────────────
class _WorkerGuardar(QThread):
    progreso = pyqtSignal(int, str)   # (porcentaje 0-100, etiqueta)
    listo    = pyqtSignal(str)        # ruta del PDF final
    error    = pyqtSignal(str)        # mensaje de error completo

    def __init__(self, ruta_pdf: Path, ruta_imagen: str,
                 num_pagina: int, destino: Path):
        # SIN parent= a propósito.
        super().__init__()
        self._ruta_pdf    = ruta_pdf
        self._ruta_imagen = ruta_imagen
        self._num_pagina  = num_pagina
        self._destino     = destino

    def run(self):
        log.debug("Worker iniciado — pdf=%s imagen=%s pagina=%s destino=%s",
                  self._ruta_pdf, self._ruta_imagen,
                  self._num_pagina, self._destino)
        ruta_pag_pdf: str | None = None
        try:
            # ── Verificaciones previas ───────────────────────────────────
            if not Path(self._ruta_imagen).exists():
                raise FileNotFoundError(
                    f"La imagen de origen no existe: {self._ruta_imagen}"
                )
            if not self._ruta_pdf.exists():
                raise FileNotFoundError(
                    f"El PDF de trabajo no existe: {self._ruta_pdf}"
                )

            # ── Etapa 1 / 4: Convertir imagen a PDF de una página ────────
            self.progreso.emit(10, "Convirtiendo imagen a PDF…")
            log.debug("Etapa 1 — iniciando conversión imagen→PDF")
            ruta_pag_pdf = _convertir_imagen_a_pdf(self._ruta_imagen)
            log.debug("Etapa 1 — conversión completada → %s", ruta_pag_pdf)
            self.progreso.emit(30, "Imagen convertida — leyendo documento…")

            # ── Etapa 2 / 4: Abrir el PDF original ──────────────────────
            log.debug("Etapa 2 — leyendo PDF original")
            try:
                from pypdf import PdfReader, PdfWriter
                log.debug("Usando pypdf")
            except ImportError:
                from PyPDF2 import PdfReader, PdfWriter  # type: ignore
                log.debug("Usando PyPDF2 (fallback)")

            lector_orig  = PdfReader(str(self._ruta_pdf))
            lector_nueva = PdfReader(ruta_pag_pdf)
            total_pags   = len(lector_orig.pages)
            log.debug("PDF original: %d páginas — reemplazando índice %d",
                      total_pags, self._num_pagina)

            if self._num_pagina >= total_pags:
                raise IndexError(
                    f"Índice de página {self._num_pagina} fuera de rango "
                    f"(el PDF tiene {total_pags} página/s)."
                )

            self.progreso.emit(45, "Leyendo documento original…")

            # ── Etapa 3 / 4: Reemplazar la página seleccionada ──────────
            self.progreso.emit(60, "Reemplazando página…")
            log.debug("Etapa 3 — construyendo PDF resultante")
            writer = PdfWriter()
            for i, pag in enumerate(lector_orig.pages):
                if i == self._num_pagina:
                    pag_nueva = lector_nueva.pages[0]
                    pag_nueva.mediabox = pag.mediabox
                    writer.add_page(pag_nueva)
                    log.debug("Página %d reemplazada", i)
                else:
                    writer.add_page(pag)

            # ── Etapa 4 / 4: Escribir el PDF resultante ─────────────────
            self.progreso.emit(85, "Escribiendo archivo final…")
            log.debug("Etapa 4 — escribiendo en %s", self._destino)
            with open(self._destino, "wb") as f_out:
                writer.write(f_out)
            log.debug("Archivo escrito OK — tamaño=%d bytes",
                      self._destino.stat().st_size)

            # Limpieza temporal
            _borrar_si_existe(ruta_pag_pdf)
            log.debug("Temporal eliminado: %s", ruta_pag_pdf)

            self.progreso.emit(100, "¡Listo!")
            log.debug("Worker terminado exitosamente — emitiendo listo")
            self.listo.emit(str(self._destino))

        except Exception as e:
            tb = traceback.format_exc()
            log.error("Error en worker:\n%s", tb)
            if ruta_pag_pdf:
                _borrar_si_existe(ruta_pag_pdf)
            self.error.emit(f"{e}\n\n─── Traceback completo ───\n{tb}")


# ─────────────────────────────────────────────────────────────────────────
#  Widget principal de la Fase 4
# ─────────────────────────────────────────────────────────────────────────
class FaseGuardar(QDialog):
    """
    Pantalla de confirmación y guardado del documento modificado.

    Señales públicas:
      guardado_listo(object / Path)  → PDF guardado correctamente
      cancelado()                    → usuario canceló

    Señal interna (NO conectar desde fuera):
      _despachar_guardado_listo(str) → encolada con QueuedConnection para
          diferir la emisión de guardado_listo al siguiente ciclo del event
          loop, evitando el crash al que llevaba invokeMethod+Q_ARG (PyQt5 API).
    """
    guardado_listo = pyqtSignal(object)   # Path
    cancelado      = pyqtSignal()

    # Señal interna para despacho encolado — reemplaza invokeMethod+Q_ARG
    _despachar_guardado_listo = pyqtSignal(str)

    def __init__(self, ruta_pdf: Path, ruta_imagen: str,
                 num_pagina: int, carpeta_firmados: Path, parent=None):
        super().__init__(parent)
        log.debug("FaseGuardar.__init__ — pdf=%s imagen=%s pagina=%d",
                  ruta_pdf, ruta_imagen, num_pagina)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint
        )
        self._ruta_pdf              = ruta_pdf
        self._ruta_imagen           = ruta_imagen
        self._num_pagina            = num_pagina
        self._carpeta_firmados      = carpeta_firmados
        self._worker: _WorkerGuardar | None = None
        self._ruta_final_pendiente: str | None = None

        # Conectar la señal interna con QueuedConnection ANTES de construir UI.
        self._despachar_guardado_listo.connect(
            self._emitir_guardado_listo,
            Qt.ConnectionType.QueuedConnection,
        )

        self._construir_ui()
        log.debug("FaseGuardar UI construida OK")

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
        self.btn_volver.clicked.connect(self._on_cancelar)
        lay_cab.addWidget(self.btn_volver)
        raiz.addWidget(cab)

        # Cuerpo
        cuerpo = QFrame()
        cuerpo.setStyleSheet("QFrame { background: #f7f6f2; }")
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

        # ── Panel de progreso ─────────────────────────────────────────
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

        self.lbl_error_detalle = QLabel("")
        self.lbl_error_detalle.setStyleSheet(
            "color: #a13544; font-size: 11px;"
        )
        self.lbl_error_detalle.setWordWrap(True)
        self.lbl_error_detalle.hide()
        lay_prog.addWidget(self.lbl_error_detalle)

        self.panel_progreso.hide()
        lay_cuerpo.addWidget(self.panel_progreso)

        lay_cuerpo.addStretch()

        raiz.addWidget(cuerpo, 1)
        raiz.addWidget(self._barra_inferior())

    def _cargar_preview(self):
        try:
            pm = QPixmap(self._ruta_imagen)
            if not pm.isNull():
                self.lbl_img.setPixmap(
                    pm.scaled(
                        90, 118,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                log.warning("Preview: QPixmap nulo para %s", self._ruta_imagen)
        except Exception as e:
            log.warning("Preview: no se pudo cargar imagen — %s", e)

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

    @pyqtSlot()
    def _on_guardar(self):
        log.debug("_on_guardar — worker activo=%s",
                  self._worker is not None and self._worker.isRunning())

        if self._worker is not None and self._worker.isRunning():
            return

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
        log.debug("Destino del guardado: %s", destino)

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

        if not Path(self._ruta_imagen).exists():
            log.error("Imagen de entrada no encontrada: %s", self._ruta_imagen)
            QMessageBox.critical(
                self, "Archivo no encontrado",
                f"No se encontró la imagen de entrada:\n{self._ruta_imagen}\n\n"
                "Volvé al paso de escaneo y seleccioná la imagen nuevamente."
            )
            return

        if not self._ruta_pdf.exists():
            log.error("PDF de trabajo no encontrado: %s", self._ruta_pdf)
            QMessageBox.critical(
                self, "Archivo no encontrado",
                f"No se encontró el PDF de trabajo:\n{self._ruta_pdf}\n\n"
                "El archivo puede haberse eliminado. Cancelá y abrí el PDF nuevamente."
            )
            return

        self._ruta_final_pendiente = None
        self._set_guardando(True)

        self._worker = _WorkerGuardar(
            self._ruta_pdf,
            self._ruta_imagen,
            self._num_pagina,
            destino,
        )
        self._worker.progreso.connect(self._on_progreso)
        self._worker.listo.connect(self._on_listo)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished_thread)
        log.debug("Worker creado — arrancando hilo")
        self._worker.start()

    def _limpiar_worker(self):
        if self._worker is not None:
            log.debug("Limpiando worker")
            self._worker.deleteLater()
            self._worker = None

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
            self.barra_progreso.setValue(0)
            self.lbl_progreso_etapa.setText("Iniciando…")
            self.lbl_error_detalle.hide()
            self.panel_progreso.show()
        else:
            self.btn_guardar.setText("Guardar documento  ✓")
            self.lbl_estado.setText("Revisá el nombre y confirmá para guardar.")
            self.lbl_estado.setStyleSheet("color: #7a7974; font-size: 13px;")

    @pyqtSlot(int, str)
    def _on_progreso(self, porcentaje: int, etiqueta: str):
        log.debug("Progreso: %d%% — %s", porcentaje, etiqueta)
        self.barra_progreso.setValue(porcentaje)
        self.lbl_progreso_etapa.setText(etiqueta)

    @pyqtSlot(str)
    def _on_listo(self, ruta_str: str):
        log.debug("Worker emitió listo — ruta=%s", ruta_str)
        self._ruta_final_pendiente = ruta_str

    @pyqtSlot()
    def _on_finished_thread(self):
        """
        Slot de QThread.finished — se ejecuta en el hilo PRINCIPAL.

        FIX v6: señal interna _despachar_guardado_listo con QueuedConnection
        en lugar de QMetaObject.invokeMethod + Q_ARG (PyQt5 API).
        """
        log.debug("_on_finished_thread — ruta_pendiente=%s",
                  self._ruta_final_pendiente)

        self._set_guardando(False)

        ruta = self._ruta_final_pendiente
        self._ruta_final_pendiente = None

        self._limpiar_worker()

        if ruta is not None:
            log.debug("Encolando _despachar_guardado_listo con ruta=%s", ruta)
            self._despachar_guardado_listo.emit(ruta)
        else:
            log.debug("ruta_pendiente es None — el worker terminó con error")

    @pyqtSlot(str)
    def _emitir_guardado_listo(self, ruta: str):
        """
        Slot invocado en el siguiente ciclo del event loop vía
        _despachar_guardado_listo (QueuedConnection).
        """
        log.debug("_emitir_guardado_listo — emitiendo guardado_listo con %s", ruta)
        try:
            self.guardado_listo.emit(Path(ruta))
        except Exception as e:
            log.error("Error al emitir guardado_listo: %s", e)

    @pyqtSlot(str)
    def _on_error(self, mensaje: str):
        """
        Slot del worker.error — se ejecuta en el hilo principal.
        No limpiamos el worker aquí; lo hace _on_finished_thread.
        """
        log.error("Worker reportó error:\n%s", mensaje)
        self._set_guardando(False)

        resumen = mensaje.split("\n")[0]
        self.lbl_progreso_etapa.setText("❌  Error al guardar")
        self.lbl_progreso_etapa.setStyleSheet(
            "color: #a13544; font-size: 13px; font-weight: 600;"
        )
        self.lbl_error_detalle.setText(resumen)
        self.lbl_error_detalle.show()
        self.panel_progreso.show()

        QMessageBox.critical(
            self,
            "Error al guardar",
            f"No se pudo guardar el documento:\n\n{resumen}\n\n"
            "Revisá la consola para el traceback completo.\n"
            "Verificá que pypdf (o PyPDF2) y Pillow estén instalados.",
        )

    @pyqtSlot()
    def _on_cancelar(self):
        if self._worker is not None and self._worker.isRunning():
            log.debug("_on_cancelar ignorado — worker activo")
            return
        log.debug("_on_cancelar — emitiendo cancelado")
        self.cancelado.emit()

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            log.debug("closeEvent bloqueado — worker activo")
            event.ignore()
            return
        if self._worker is not None:
            log.debug("closeEvent — esperando worker con wait()")
            self._worker.wait()
            self._limpiar_worker()
        log.debug("closeEvent aceptado")
        super().closeEvent(event)
