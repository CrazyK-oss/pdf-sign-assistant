"""
modules/fase_guardar.py
=======================
Fase final del flujo: confirmación y guardado del PDF modificado.

Recibe un TrabajoFirma ya completo (todas las páginas elegidas con su
imagen) y produce el PDF final en pdfs_firmados/.

Emite:
  - guardado_listo(Path)  → ruta del PDF final
  - cancelado()           → el usuario volvió atrás

Multipágina
-----------
El worker reemplaza TODAS las páginas del trabajo en una sola pasada de
escritura, aplicando la rotación elegida en cada imagen. El progreso se
reparte entre las páginas, así que con 10 hojas la barra avanza de a
poco en vez de quedarse clavada.

Al guardar se escriben metadatos con las páginas firmadas (`/PSAPaginas`).
Eso permite que, al reabrir el documento más tarde para enviarlo por
correo, el resumen diga las páginas reales en vez del "página 1" fijo
que se mostraba antes.

Correcciones que sostiene esta versión
--------------------------------------
* img2pdf corre en un SUBPROCESO aislado: puede crashear a nivel de
  extensión C (pikepdf/libjpeg), y ahí ningún try/except de Python
  llega a atrapar nada.
* Ese subproceso NO se lanza en modo congelado: `sys.executable` dentro
  de un .exe de PyInstaller es la propia app, así que "convertir la
  imagen" abría una segunda instancia del programa.
* La emisión de guardado_listo se difiere con QueuedConnection.
* logging.basicConfig() no se llama al importar.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from modules.theme import SIZE, SPACE, repolish, theme_signals
from modules.trabajo import TrabajoFirma, formatear_paginas
from modules.ui import (
    AreaScroll,
    BarraInferior,
    BarraSuperior,
    boton,
    etiqueta,
    tarjeta,
)

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

CARACTERES_INVALIDOS = set('/\\:*?"<>|')

# Clave propia en el diccionario Info del PDF con las páginas firmadas
CLAVE_META_PAGINAS = "/PSAPaginas"


# ─────────────────────────────────────────────────────────────────────────
#  Script auxiliar que corre img2pdf en subproceso aislado
# ─────────────────────────────────────────────────────────────────────────
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
    if modo in ("RGB", "L"):
        return img
    if modo in ("RGBA", "PA"):
        from PIL import Image as _Image
        fondo = _Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        fondo.paste(rgba, mask=rgba.split()[3])
        return fondo
    if modo == "LA":
        return img.convert("L")
    return img.convert("RGB")


def aplicar_rotacion(ruta_imagen: str, grados: int) -> tuple[str, bool]:
    """Devuelve (ruta, es_temporal) con la imagen ya rotada.

    Rota en sentido horario para coincidir con lo que muestra la vista
    previa (QTransform().rotate() gira en horario; PIL, en antihorario).
    El archivo original nunca se toca: se escribe una copia temporal.
    """
    grados = int(grados) % 360
    if grados == 0:
        return ruta_imagen, False

    from PIL import Image
    with Image.open(ruta_imagen) as img:
        rotada = img.rotate(-grados, expand=True)
        rotada = _normalizar_modo_pillow(rotada)
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        # Conserva el DPI para que la página resultante mida lo mismo
        dpi = img.info.get("dpi")
        if dpi:
            rotada.save(tmp.name, "PNG", dpi=dpi)
        else:
            rotada.save(tmp.name, "PNG")
    log.debug("Rotación %d° aplicada → %s", grados, tmp.name)
    return tmp.name, True


def _imagen_a_pdf_reportlab(ruta_imagen: str) -> str:
    """Convierte imagen a PDF de una página con reportlab (motor principal:
    es el más robusto en Windows con JPG/PNG/BMP)."""
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    with Image.open(ruta_imagen) as img:
        ancho_px, alto_px = img.size
        dpi = img.info.get("dpi", (150, 150))
        if isinstance(dpi, (int, float)):
            dpi = (dpi, dpi)
        dpi_x = dpi[0] if dpi[0] > 0 else 150
        dpi_y = dpi[1] if dpi[1] > 0 else 150

    ancho_pt = ancho_px * 72.0 / dpi_x
    alto_pt = alto_px * 72.0 / dpi_y

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()

    c = canvas.Canvas(tmp.name, pagesize=(ancho_pt, alto_pt))
    c.drawImage(ImageReader(ruta_imagen), 0, 0,
                width=ancho_pt, height=alto_pt, preserveAspectRatio=False)
    c.save()

    if Path(tmp.name).stat().st_size == 0:
        _borrar_si_existe(tmp.name)
        raise RuntimeError("reportlab generó un PDF vacío (0 bytes)")
    return tmp.name


def _imagen_a_pdf_pillow(ruta_imagen: str) -> str:
    """Convierte una imagen a PDF de una página usando Pillow."""
    from PIL import Image
    with Image.open(ruta_imagen) as img_orig:
        img = _normalizar_modo_pillow(img_orig)
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.close()
        img.save(tmp.name, "PDF", resolution=150)
    return tmp.name


def _imagen_a_pdf_img2pdf(ruta_imagen: str) -> str:
    """Convierte con img2pdf en un subproceso aislado.

    En modo congelado (PyInstaller) se salta: sys.executable apunta al
    propio .exe y lanzar `-c` abriría otra instancia de la aplicación.
    """
    if getattr(sys, "frozen", False):
        raise RuntimeError("img2pdf no se usa en modo congelado (.exe)")

    try:
        import importlib
        importlib.import_module("img2pdf")
    except ImportError as exc:
        raise ImportError("img2pdf no está instalado") from exc

    tmp_out = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_out.close()

    try:
        resultado = subprocess.run(
            [sys.executable, "-c", _IMG2PDF_WORKER_SCRIPT,
             ruta_imagen, tmp_out.name],
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        _borrar_si_existe(tmp_out.name)
        raise RuntimeError("img2pdf: timeout tras 60 s") from exc
    except Exception as exc:
        _borrar_si_existe(tmp_out.name)
        raise RuntimeError(f"img2pdf: error al lanzar subproceso — {exc}") from exc

    if resultado.returncode != 0:
        stderr = resultado.stderr.decode(errors="replace").strip()
        _borrar_si_existe(tmp_out.name)
        raise RuntimeError(
            f"img2pdf terminó con código {resultado.returncode}. stderr: {stderr}")

    if Path(tmp_out.name).stat().st_size == 0:
        _borrar_si_existe(tmp_out.name)
        raise RuntimeError("img2pdf generó un PDF vacío (0 bytes)")
    return tmp_out.name


def _borrar_si_existe(ruta: str | None) -> None:
    try:
        if ruta and Path(ruta).exists():
            os.remove(ruta)
    except OSError:
        pass


def _convertir_imagen_a_pdf(ruta_imagen: str, rotacion: int = 0) -> str:
    """Convierte una imagen (con su rotación) a un PDF de una página.

    Intenta reportlab → img2pdf (subproceso) → Pillow, en ese orden.
    """
    ruta_rotada, temporal = aplicar_rotacion(ruta_imagen, rotacion)
    try:
        for nombre, motor in (
            ("reportlab", _imagen_a_pdf_reportlab),
            ("img2pdf", _imagen_a_pdf_img2pdf),
        ):
            try:
                ruta = motor(ruta_rotada)
                log.debug("Conversión con %s OK → %s", nombre, ruta)
                return ruta
            except ImportError:
                log.debug("%s no disponible, probando el siguiente motor", nombre)
            except Exception as e:                   # noqa: BLE001
                log.warning("%s falló (%s: %s) — probando el siguiente motor",
                            nombre, type(e).__name__, e)

        log.debug("Usando Pillow como último fallback")
        return _imagen_a_pdf_pillow(ruta_rotada)
    finally:
        if temporal:
            _borrar_si_existe(ruta_rotada)


# ─────────────────────────────────────────────────────────────────────────
#  Worker: arma el PDF final en hilo secundario
# ─────────────────────────────────────────────────────────────────────────
class _WorkerGuardar(QThread):
    progreso = pyqtSignal(int, str)   # (porcentaje 0-100, etiqueta)
    listo    = pyqtSignal(str)        # ruta del PDF final
    error    = pyqtSignal(str)        # mensaje de error completo

    def __init__(self, trabajo: TrabajoFirma, destino: Path):
        super().__init__()            # SIN parent= a propósito
        self._trabajo = trabajo
        self._destino = destino

    def run(self):
        paginas = list(self._trabajo.paginas)
        log.debug("Worker iniciado — pdf=%s paginas=%s destino=%s",
                  self._trabajo.ruta_pdf, paginas, self._destino)
        temporales: list[str] = []
        try:
            if not self._trabajo.ruta_pdf.exists():
                raise FileNotFoundError(
                    f"El PDF de trabajo no existe: {self._trabajo.ruta_pdf}")
            if not paginas:
                raise ValueError("No hay páginas seleccionadas.")

            faltantes = self._trabajo.paginas_pendientes()
            if faltantes:
                raise ValueError(
                    "Faltan imágenes para las páginas "
                    f"{formatear_paginas(faltantes)}.")

            # ── 1: cada imagen → PDF de una página ──────────────────────
            paginas_pdf: dict[int, str] = {}
            total = len(paginas)
            for i, pagina in enumerate(paginas):
                ruta_img = self._trabajo.imagenes[pagina]
                if not Path(ruta_img).exists():
                    raise FileNotFoundError(
                        f"No se encuentra la imagen de la página {pagina + 1}:\n"
                        f"{ruta_img}")

                pct = 5 + int(i / total * 55)
                self.progreso.emit(
                    pct, f"Convirtiendo la página {pagina + 1} "
                         f"({i + 1} de {total})…")
                ruta_pdf_pag = _convertir_imagen_a_pdf(
                    ruta_img, self._trabajo.rotacion(pagina))
                paginas_pdf[pagina] = ruta_pdf_pag
                temporales.append(ruta_pdf_pag)

            # ── 2: abrir el PDF original ────────────────────────────────
            self.progreso.emit(62, "Leyendo el documento original…")
            try:
                from pypdf import PdfReader, PdfWriter
            except ImportError:
                from PyPDF2 import PdfReader, PdfWriter  # type: ignore

            lector_orig = PdfReader(str(self._trabajo.ruta_pdf))
            total_pags = len(lector_orig.pages)

            fuera = [p for p in paginas if p >= total_pags]
            if fuera:
                raise IndexError(
                    f"El documento tiene {total_pags} página(s); se pidió "
                    f"reemplazar {formatear_paginas(fuera)}.")

            # Los lectores de las páginas nuevas deben seguir vivos hasta
            # escribir: pypdf resuelve los objetos de forma perezosa.
            lectores_nuevos = {p: PdfReader(r) for p, r in paginas_pdf.items()}

            # ── 3: reemplazar todas las páginas elegidas ────────────────
            self.progreso.emit(72, f"Reemplazando {total} página(s)…")
            writer = PdfWriter()
            reemplazadas = 0
            for i, pag in enumerate(lector_orig.pages):
                if i in lectores_nuevos:
                    pag_nueva = lectores_nuevos[i].pages[0]
                    pag_nueva.mediabox = pag.mediabox
                    writer.add_page(pag_nueva)
                    reemplazadas += 1
                else:
                    writer.add_page(pag)

            # ── 4: metadatos con las páginas firmadas ───────────────────
            self.progreso.emit(85, "Escribiendo metadatos…")
            try:
                meta = dict(lector_orig.metadata or {})
                meta.update({
                    "/Producer": "PDF Sign Assistant",
                    CLAVE_META_PAGINAS: ",".join(str(p) for p in paginas),
                })
                writer.add_metadata(meta)
            except Exception as e:                   # noqa: BLE001
                # Un Info dict raro no debe impedir guardar el documento
                log.warning("No se pudieron escribir los metadatos: %s", e)

            # ── 5: escribir el resultado ────────────────────────────────
            self.progreso.emit(92, "Escribiendo el archivo final…")
            self._destino.parent.mkdir(parents=True, exist_ok=True)
            with open(self._destino, "wb") as f_out:
                writer.write(f_out)
            log.debug("Archivo escrito OK — %d páginas reemplazadas, %d bytes",
                      reemplazadas, self._destino.stat().st_size)

            self.progreso.emit(100, "¡Listo!")
            self.listo.emit(str(self._destino))

        except Exception as e:                       # noqa: BLE001
            tb = traceback.format_exc()
            log.error("Error en worker:\n%s", tb)
            self.error.emit(f"{e}\n\n─── Traceback completo ───\n{tb}")
        finally:
            for t in temporales:
                _borrar_si_existe(t)


def leer_paginas_firmadas(ruta_pdf: Path) -> list[int]:
    """Lee del PDF las páginas que firmó esta app.

    Devuelve [] si el documento no tiene el metadato (por ejemplo, si lo
    firmó una versión anterior).
    """
    try:
        from pypdf import PdfReader
        meta = PdfReader(str(ruta_pdf)).metadata or {}
        crudo = meta.get(CLAVE_META_PAGINAS)
        if not crudo:
            return []
        return sorted({
            int(x) for x in str(crudo).split(",")
            if x.strip().lstrip("-").isdigit()
        })
    except Exception:                                # noqa: BLE001
        return []


# ─────────────────────────────────────────────────────────────────────────
#  Pantalla de guardado
# ─────────────────────────────────────────────────────────────────────────
class FaseGuardar(QDialog):
    """
    Señales públicas:
      guardado_listo(object / Path)  → PDF guardado correctamente
      cancelado()                    → el usuario volvió atrás

    Señal interna (NO conectar desde fuera):
      _despachar_guardado_listo(str) → encolada con QueuedConnection para
          diferir la emisión de guardado_listo al siguiente ciclo del
          event loop.
    """

    guardado_listo = pyqtSignal(object)   # Path
    cancelado      = pyqtSignal()
    _despachar_guardado_listo = pyqtSignal(str)

    def __init__(self, trabajo: TrabajoFirma, carpeta_firmados: Path, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window |
                            Qt.WindowType.WindowCloseButtonHint)
        self.setObjectName("pantalla")
        self.setMinimumSize(520, 460)

        self.trabajo = trabajo
        self._carpeta_firmados = carpeta_firmados
        self._worker: _WorkerGuardar | None = None
        self._ruta_final_pendiente: str | None = None

        # Conectar la señal interna ANTES de construir la UI.
        self._despachar_guardado_listo.connect(
            self._emitir_guardado_listo, Qt.ConnectionType.QueuedConnection)

        self._construir_ui()
        theme_signals.changed.connect(self._on_tema_cambiado)

    # ── UI ────────────────────────────────────────────────────────────
    def _construir_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        nombre_pdf = os.path.basename(str(self.trabajo.ruta_pdf))
        cantidad = self.trabajo.cantidad
        plural = "s" if cantidad != 1 else ""
        cab = BarraSuperior(
            f"Guardar  ·  {cantidad} página{plural} "
            f"({self.trabajo.etiqueta_paginas()})  ·  {nombre_pdf}")
        self.btn_volver = boton("←  Volver al escaneo", variant="ghost",
                                tooltip="Volver al paso anterior (Esc)",
                                on_click=self._on_cancelar)
        cab.agregar(self.btn_volver)
        raiz.addWidget(cab)

        cuerpo = AreaScroll(margenes=(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"]),
                            spacing=SPACE["md"])
        lay = cuerpo.lay
        lay.addWidget(self._panel_paginas())
        lay.addWidget(self._panel_nombre())
        lay.addWidget(self._panel_progreso())
        lay.addStretch()
        raiz.addWidget(cuerpo, 1)

        self.pie = BarraInferior("Revisá el nombre y confirmá para guardar.")
        self.btn_guardar = boton("Guardar documento  ✓", variant="success",
                                 height=SIZE["btn_lg"],
                                 tooltip="Guardar el PDF firmado (Enter)",
                                 on_click=self._on_guardar)
        self.pie.agregar(self.btn_guardar)
        raiz.addWidget(self.pie)

        # La validación se conecta al final: durante la construcción el
        # setText() inicial dispararía el slot antes de que existan el
        # label de error y el botón que toca.
        self.input_nombre.textChanged.connect(self._validar_nombre)
        self._validar_nombre()

    def _panel_paginas(self) -> QFrame:
        """Resumen de qué imagen va en cada página."""
        panel, lay = tarjeta(acento=True, padding=SPACE["md"], spacing=SPACE["sm"])
        cantidad = self.trabajo.cantidad
        plural = "s" if cantidad != 1 else ""
        lay.addWidget(etiqueta(
            f"{cantidad} PÁGINA{plural.upper()} A REEMPLAZAR", rol="seccion"))

        for pagina in self.trabajo.paginas:
            ruta = self.trabajo.imagenes.get(pagina, "")
            rotacion = self.trabajo.rotacion(pagina)

            fila = QHBoxLayout()
            fila.setSpacing(SPACE["md"])

            thumb = QLabel()
            thumb.setObjectName("lienzoPagina")
            thumb.setFixedSize(52, 68)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pm = QPixmap(ruta)
            if not pm.isNull():
                if rotacion:
                    pm = pm.transformed(QTransform().rotate(rotacion),
                                        Qt.TransformationMode.SmoothTransformation)
                thumb.setPixmap(pm.scaled(
                    52, 68, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            fila.addWidget(thumb)

            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(etiqueta(f"Página {pagina + 1}", rol="subtitulo"))
            detalle = os.path.basename(ruta)
            if rotacion:
                detalle += f"  ·  rotada {rotacion}°"
            col.addWidget(etiqueta(detalle, rol="hint", wrap=True))
            col.addStretch()
            fila.addLayout(col, 1)

            contenedor = QFrame()
            contenedor.setLayout(fila)
            lay.addWidget(contenedor)

        return panel

    def _panel_nombre(self) -> QFrame:
        panel, lay = tarjeta(padding=SPACE["lg"], spacing=SPACE["sm"])
        lay.addWidget(etiqueta("Nombre del documento a guardar", rol="subtitulo"))
        lay.addWidget(etiqueta(
            f"Se guardará en:  {self._carpeta_firmados}", rol="hint", wrap=True))

        fila = QHBoxLayout()
        fila.setSpacing(SPACE["sm"])

        self.input_nombre = QLineEdit()
        self.input_nombre.setMinimumHeight(SIZE["input"])
        self.input_nombre.setPlaceholderText("ej: contrato_firmado")
        self.input_nombre.setClearButtonEnabled(True)
        self.input_nombre.returnPressed.connect(self._on_guardar)

        stem = Path(str(self.trabajo.ruta_pdf)).stem
        if stem.startswith("reedit_"):
            stem = stem[len("reedit_"):]
        self.input_nombre.setText(stem)
        self.input_nombre.selectAll()
        fila.addWidget(self.input_nombre, 1)
        fila.addWidget(etiqueta(".pdf", rol="hint"))
        lay.addLayout(fila)

        self.lbl_error_nombre = etiqueta("", rol="error", wrap=True)
        self.lbl_error_nombre.hide()
        lay.addWidget(self.lbl_error_nombre)
        return panel

    def _panel_progreso(self) -> QFrame:
        self.panel_progreso, lay = tarjeta(padding=SPACE["md"], spacing=SPACE["sm"])
        self.lbl_progreso_etapa = etiqueta("Iniciando…", rol="ok")
        lay.addWidget(self.lbl_progreso_etapa)

        self.barra_progreso = QProgressBar()
        self.barra_progreso.setRange(0, 100)
        self.barra_progreso.setValue(0)
        self.barra_progreso.setTextVisible(False)
        lay.addWidget(self.barra_progreso)

        self.lbl_error_detalle = etiqueta("", rol="error", wrap=True)
        self.lbl_error_detalle.hide()
        lay.addWidget(self.lbl_error_detalle)

        self.panel_progreso.hide()
        return self.panel_progreso

    def _on_tema_cambiado(self, _modo: str):
        pass   # los estilos vienen del QSS; nada local que repintar

    # ── Validación ────────────────────────────────────────────────────
    def _validar_nombre(self, texto: str = "") -> str | None:
        """Devuelve el nombre normalizado, o None si es inválido.
        Muestra el error debajo del campo en tiempo real."""
        nombre = (texto or self.input_nombre.text()).strip()
        error = ""
        if not nombre:
            error = "El nombre no puede estar vacío."
        elif any(c in nombre for c in CARACTERES_INVALIDOS):
            error = 'El nombre no puede contener: / \\ : * ? " < > |'

        self.lbl_error_nombre.setText(error)
        self.lbl_error_nombre.setVisible(bool(error))
        self.input_nombre.setProperty("invalid", "true" if error else "false")
        repolish(self.input_nombre)
        self.btn_guardar.setEnabled(not error)

        if error:
            return None
        return nombre if nombre.lower().endswith(".pdf") else f"{nombre}.pdf"

    # ── Guardado ──────────────────────────────────────────────────────
    @pyqtSlot()
    def _on_guardar(self):
        if self._worker is not None and self._worker.isRunning():
            return

        nombre = self._validar_nombre()
        if nombre is None:
            self.input_nombre.setFocus()
            return

        if not self.trabajo.completo:
            QMessageBox.warning(
                self, "Faltan imágenes",
                "Todavía hay páginas sin imagen asignada:\n"
                f"{formatear_paginas(self.trabajo.paginas_pendientes())}")
            return

        destino = self._carpeta_firmados / nombre
        if destino.exists():
            resp = QMessageBox.question(
                self, "Archivo existente",
                f"Ya existe un archivo con ese nombre:\n{nombre}\n\n"
                "¿Querés reemplazarlo?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if resp != QMessageBox.StandardButton.Yes:
                return

        faltan_img = [p for p in self.trabajo.paginas
                      if not Path(self.trabajo.imagenes[p]).exists()]
        if faltan_img:
            QMessageBox.critical(
                self, "Archivos no encontrados",
                "No se encuentran las imágenes de las páginas "
                f"{formatear_paginas(faltan_img)}.\n\n"
                "Volvé al paso de escaneo y asignalas de nuevo.")
            return

        if not self.trabajo.ruta_pdf.exists():
            QMessageBox.critical(
                self, "Archivo no encontrado",
                f"No se encontró el PDF de trabajo:\n{self.trabajo.ruta_pdf}\n\n"
                "Cancelá y abrí el PDF nuevamente.")
            return

        self._ruta_final_pendiente = None
        self._set_guardando(True)

        self._worker = _WorkerGuardar(self.trabajo, destino)
        self._worker.progreso.connect(self._on_progreso)
        self._worker.listo.connect(self._on_listo)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished_thread)
        self._worker.start()

    def _limpiar_worker(self):
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _set_guardando(self, guardando: bool):
        self.btn_guardar.setEnabled(not guardando)
        self.btn_volver.setEnabled(not guardando)
        self.input_nombre.setEnabled(not guardando)

        if guardando:
            self.btn_guardar.setText("Guardando…")
            self.pie.set_estado("Procesando, no cierres la ventana…", rol="ok")
            self.barra_progreso.setValue(0)
            self.lbl_progreso_etapa.setText("Iniciando…")
            self.lbl_progreso_etapa.setProperty("rol", "ok")
            repolish(self.lbl_progreso_etapa)
            self.lbl_error_detalle.hide()
            self.panel_progreso.show()
        else:
            self.btn_guardar.setText("Guardar documento  ✓")
            self.pie.set_estado("Revisá el nombre y confirmá para guardar.")

    @pyqtSlot(int, str)
    def _on_progreso(self, porcentaje: int, etapa: str):
        self.barra_progreso.setValue(porcentaje)
        self.lbl_progreso_etapa.setText(etapa)

    @pyqtSlot(str)
    def _on_listo(self, ruta_str: str):
        self._ruta_final_pendiente = ruta_str

    @pyqtSlot()
    def _on_finished_thread(self):
        """Slot de QThread.finished — corre en el hilo PRINCIPAL."""
        self._set_guardando(False)
        ruta = self._ruta_final_pendiente
        self._ruta_final_pendiente = None
        self._limpiar_worker()
        if ruta is not None:
            self._despachar_guardado_listo.emit(ruta)

    @pyqtSlot(str)
    def _emitir_guardado_listo(self, ruta: str):
        """Invocado en el siguiente ciclo del event loop (QueuedConnection)."""
        try:
            self.guardado_listo.emit(Path(ruta))
        except Exception as e:                       # noqa: BLE001
            log.error("Error al emitir guardado_listo: %s", e)

    @pyqtSlot(str)
    def _on_error(self, mensaje: str):
        log.error("Worker reportó error:\n%s", mensaje)
        self._set_guardando(False)

        resumen = mensaje.split("\n")[0]
        self.lbl_progreso_etapa.setText("❌  Error al guardar")
        self.lbl_progreso_etapa.setProperty("rol", "error")
        repolish(self.lbl_progreso_etapa)
        self.lbl_error_detalle.setText(resumen)
        self.lbl_error_detalle.show()
        self.panel_progreso.show()

        QMessageBox.critical(
            self, "Error al guardar",
            f"No se pudo guardar el documento:\n\n{resumen}\n\n"
            "Revisá el log para el traceback completo.")

    @pyqtSlot()
    def _on_cancelar(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self.cancelado.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._on_cancelar()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            event.ignore()
            return
        if self._worker is not None:
            self._worker.wait()
            self._limpiar_worker()
        try:
            theme_signals.changed.disconnect(self._on_tema_cambiado)
        except (TypeError, RuntimeError):
            pass
        super().closeEvent(event)
