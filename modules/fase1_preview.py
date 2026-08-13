"""
modules/fase1_preview.py
============================================================
Fase 1: grid de páginas del PDF para elegir cuáles se firman.

Ahora la selección es MÚLTIPLE: se pueden firmar varias páginas en una
misma sesión. Formas de seleccionar:
  - Clic en la tarjeta (alterna)
  - Shift+clic para un rango desde la última tocada
  - Ctrl+A / botón "Todas", botón "Ninguna"
  - Campo de texto con expresiones tipo "1, 3, 5-8"
  - Doble clic (o Espacio) abre la vista previa grande, donde también
    se puede seleccionar y navegar entre páginas

Puntos técnicos que sostiene este módulo
----------------------------------------
* THREAD-SAFETY: el worker emite QImage, no QPixmap. Qt sólo permite
  construir QPixmap en el hilo de GUI.
* Las tarjetas se crean una sola vez, apenas se conoce el total de
  páginas, y se rellenan a medida que llegan los renders.
* Grid responsive: columnas y ancho de tarjeta se recalculan al
  redimensionar (con debounce) sin volver a renderizar el PDF.
* Estilos 100% del tema (modo oscuro y cambio en caliente).
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules.theme import SIZE, SPACE, THEME, repolish, theme_signals
from modules.trabajo import formatear_paginas, parsear_paginas
from modules.ui import BarraInferior, BarraSuperior, boton, etiqueta

try:
    import fitz  # PyMuPDF
    PYMUPDF_DISPONIBLE = True
except ImportError:
    PYMUPDF_DISPONIBLE = False


# Ancho al que se renderiza el thumbnail (px lógicos). Se renderiza una
# sola vez a este ancho y luego se escala en memoria al reacomodar el
# grid: cambiar el tamaño de la ventana no vuelve a tocar el PDF.
THUMB_W_MAX = 210
THUMB_W_MIN = 160
RATIO_FALLBACK = 1.294   # A4 alto/ancho, usado mientras no hay render

# Ancho de render de la vista previa grande
PREVIEW_W = 900


# ─────────────────────────────────────────────────────────────
#  Worker: renderiza thumbnails en hilo separado (no bloquea UI)
# ─────────────────────────────────────────────────────────────
class RenderWorker(QThread):
    """Renderiza las páginas del PDF a QImage en segundo plano.

    Emite QImage (no QPixmap): QPixmap sólo puede construirse en el
    hilo de GUI. La conversión se hace del lado del receptor.
    """

    total_paginas   = pyqtSignal(int)            # se emite apenas se abre el PDF
    thumbnail_listo = pyqtSignal(int, QImage)    # (num_pagina 0-based, imagen)
    terminado       = pyqtSignal(int)            # total de páginas renderizadas
    fallo           = pyqtSignal(str)            # error al abrir/renderizar

    def __init__(self, ruta_pdf: str, thumb_w: int = THUMB_W_MAX,
                 escala_dpr: float = 1.0):
        super().__init__()
        self.ruta_pdf = ruta_pdf
        self.thumb_w = max(32, int(thumb_w * max(1.0, escala_dpr)))
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True
        self.requestInterruption()

    def run(self):
        if not PYMUPDF_DISPONIBLE:
            self.fallo.emit("PyMuPDF no está instalado.")
            self.terminado.emit(0)
            return

        doc = None
        renderizadas = 0
        try:
            doc = fitz.open(self.ruta_pdf)
            total = doc.page_count
            self.total_paginas.emit(total)

            for i in range(total):
                if self._cancelado or self.isInterruptionRequested():
                    break
                pagina = doc.load_page(i)
                ancho_pt = pagina.rect.width or 1
                zoom = self.thumb_w / ancho_pt
                pix = pagina.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                # copy() desacopla la QImage del buffer de fitz, que se
                # libera al pasar a la siguiente página.
                img = QImage(
                    pix.samples, pix.width, pix.height,
                    pix.stride, QImage.Format.Format_RGB888,
                ).copy()
                self.thumbnail_listo.emit(i, img)
                renderizadas += 1

            self.terminado.emit(renderizadas)
        except Exception as e:                       # noqa: BLE001
            self.fallo.emit(str(e))
            self.terminado.emit(renderizadas)
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────
#  Vista previa grande de una página
# ─────────────────────────────────────────────────────────────
class DialogoVistaPagina(QDialog):
    """Muestra una página a tamaño grande para poder decidir.

    Los thumbnails del grid son deliberadamente chicos; con documentos
    parecidos entre sí (formularios, actas) no alcanzan para saber cuál
    es la hoja a firmar. Acá se ve la página completa, se navega con
    las flechas y se puede marcar/desmarcar sin volver al grid.
    """

    seleccion_cambiada = pyqtSignal(int, bool)   # (pagina, seleccionada)

    def __init__(self, ruta_pdf: str, pagina: int, total: int,
                 seleccionadas: set[int], parent=None):
        super().__init__(parent)
        self.ruta_pdf = ruta_pdf
        self.pagina = pagina
        self.total = total
        self.seleccionadas = set(seleccionadas)

        self.setObjectName("pantalla")
        self.setWindowTitle("Vista previa")
        self.setMinimumSize(460, 460)
        self.resize(760, 820)
        self._construir_ui()
        self._cargar_pagina()

    def _construir_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        self.cabecera = BarraSuperior("")
        self.cabecera.agregar(boton("✕", variant="ghost", fixed_w=40,
                                    tooltip="Cerrar (Esc)", on_click=self.accept))
        raiz.addWidget(self.cabecera)

        self.lbl_img = QLabel()
        self.lbl_img.setObjectName("lienzoPagina")
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_img.setMinimumHeight(200)
        contenedor = QWidget()
        lay_c = QVBoxLayout(contenedor)
        lay_c.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        lay_c.addWidget(self.lbl_img, 1)
        raiz.addWidget(contenedor, 1)

        self.pie = BarraInferior("")
        self.btn_anterior = boton("←", variant="ghost", fixed_w=44,
                                  tooltip="Página anterior",
                                  on_click=lambda: self._navegar(-1))
        self.btn_siguiente = boton("→", variant="ghost", fixed_w=44,
                                   tooltip="Página siguiente",
                                   on_click=lambda: self._navegar(1))
        self.btn_marcar = boton("", height=SIZE["btn_lg"], min_w=180,
                                on_click=self._alternar)
        self.pie.agregar(self.btn_anterior)
        self.pie.agregar(self.btn_siguiente)
        self.pie.agregar(self.btn_marcar)
        raiz.addWidget(self.pie)

    def _cargar_pagina(self):
        self.cabecera.set_titulo(f"Página {self.pagina + 1} de {self.total}")
        self.btn_anterior.setEnabled(self.pagina > 0)
        self.btn_siguiente.setEnabled(self.pagina < self.total - 1)
        self._actualizar_boton()

        if not PYMUPDF_DISPONIBLE:
            self.lbl_img.setText("PyMuPDF no está instalado.")
            return
        try:
            with fitz.open(self.ruta_pdf) as doc:
                pag = doc.load_page(self.pagina)
                zoom = PREVIEW_W / (pag.rect.width or 1)
                pix = pag.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                img = QImage(pix.samples, pix.width, pix.height,
                             pix.stride, QImage.Format.Format_RGB888).copy()
            self._pixmap = QPixmap.fromImage(img)
            self._reescalar()
        except Exception as e:                       # noqa: BLE001
            self.lbl_img.setText(f"No se pudo renderizar la página:\n{e}")

    def _reescalar(self):
        pm = getattr(self, "_pixmap", None)
        if pm is None or pm.isNull():
            return
        self.lbl_img.setPixmap(pm.scaled(
            self.lbl_img.width(), self.lbl_img.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def _actualizar_boton(self):
        activa = self.pagina in self.seleccionadas
        self.btn_marcar.setText("✓  Seleccionada — quitar" if activa
                                else "Seleccionar esta página")
        self.btn_marcar.setProperty("variant", "danger" if activa else "primary")
        repolish(self.btn_marcar)
        self.pie.set_estado(
            f"{len(self.seleccionadas)} seleccionada(s)  ·  "
            "Espacio marca · ← → navega · Esc cierra", rol="hint")

    def _alternar(self):
        activa = self.pagina not in self.seleccionadas
        if activa:
            self.seleccionadas.add(self.pagina)
        else:
            self.seleccionadas.discard(self.pagina)
        self.seleccion_cambiada.emit(self.pagina, activa)
        self._actualizar_boton()

    def _navegar(self, delta: int):
        destino = self.pagina + delta
        if 0 <= destino < self.total:
            self.pagina = destino
            self._cargar_pagina()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reescalar()

    def keyPressEvent(self, event):
        tecla = event.key()
        if tecla == Qt.Key.Key_Space:
            self._alternar()
            return
        if tecla in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._navegar(-1)
            return
        if tecla in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._navegar(1)
            return
        super().keyPressEvent(event)


# ─────────────────────────────────────────────────────────────
#  Tarjeta individual de página
# ─────────────────────────────────────────────────────────────
class TarjetaPagina(QFrame):
    """Tarjeta clicable de una página. Sin estilos propios: todo el
    aspecto (normal / hover / activa / foco) sale del QSS del tema."""

    clicada     = pyqtSignal(int, object)   # (pagina, modificadores)
    ampliada    = pyqtSignal(int)           # doble clic → vista grande
    enfocada    = pyqtSignal(int)

    def __init__(self, num_pagina: int, ancho: int = THUMB_W_MAX, parent=None):
        super().__init__(parent)
        self.num_pagina = num_pagina
        self._pixmap_fuente: QPixmap | None = None
        self._ratio = RATIO_FALLBACK
        self._ancho = ancho

        self.setObjectName("tarjetaPagina")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty("activa", "false")
        self.setAccessibleName(f"Página {num_pagina + 1}")
        self.setToolTip("Clic para seleccionar · doble clic para ampliar")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE["sm"], SPACE["sm"], SPACE["sm"], SPACE["xs"])
        lay.setSpacing(SPACE["xs"])

        self.lbl_img = QLabel()
        self.lbl_img.setObjectName("lienzoPagina")
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_img.setScaledContents(False)
        lay.addWidget(self.lbl_img)

        fila = QHBoxLayout()
        fila.setSpacing(SPACE["xs"])
        fila.addStretch()
        self.lbl_check = etiqueta("✓", rol="ok")
        self.lbl_check.setVisible(False)
        fila.addWidget(self.lbl_check)
        self.lbl_num = etiqueta(f"Página {num_pagina + 1}", rol="cuerpo")
        fila.addWidget(self.lbl_num)
        fila.addStretch()
        lay.addLayout(fila)

        self.set_ancho(ancho)

    # ── Tamaño / responsive ────────────────────────
    def set_ancho(self, ancho: int) -> None:
        """Cambia el ancho de la tarjeta reescalando el thumbnail ya
        renderizado (no vuelve a leer el PDF)."""
        self._ancho = ancho
        self.setFixedWidth(ancho)
        ancho_img = ancho - SPACE["sm"] * 2
        alto_img = int(ancho_img * self._ratio)
        self.lbl_img.setFixedHeight(alto_img)
        self._pintar(ancho_img, alto_img)

    def _pintar(self, ancho_img: int, alto_img: int) -> None:
        if self._pixmap_fuente is None:
            self.lbl_img.setPixmap(self._skeleton(ancho_img, alto_img))
            return
        dpr = self._pixmap_fuente.devicePixelRatio() or 1.0
        escalado = self._pixmap_fuente.scaled(
            int(ancho_img * dpr), int(alto_img * dpr),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        escalado.setDevicePixelRatio(dpr)
        self.lbl_img.setPixmap(escalado)

    # ── Skeleton mientras carga ────────────────────
    def _skeleton(self, ancho: int, alto: int) -> QPixmap:
        pm = QPixmap(max(1, ancho), max(1, alto))
        pm.fill(QColor(THEME["surface_3"]))
        p = QPainter(pm)
        p.setBrush(QColor(THEME["border"]))
        p.setPen(Qt.PenStyle.NoPen)
        margen = max(8, ancho // 8)
        y = margen
        fila = 0
        while y < alto - margen:
            w = (ancho - margen * 2) if fila % 3 else int((ancho - margen * 2) * 0.65)
            p.drawRoundedRect(margen, y, w, 6, 3, 3)
            y += 18
            fila += 1
        p.end()
        return pm

    # ── Recibe el render real ──────────────────────
    def set_imagen(self, imagen: QImage, dpr: float = 1.0) -> None:
        if imagen.isNull():
            return
        pm = QPixmap.fromImage(imagen)
        pm.setDevicePixelRatio(max(1.0, dpr))
        self._pixmap_fuente = pm
        ancho_pm = pm.width() / max(1.0, dpr)
        alto_pm = pm.height() / max(1.0, dpr)
        if ancho_pm > 0:
            self._ratio = alto_pm / ancho_pm
        self.set_ancho(self._ancho)

    # ── Estado visual ──────────────────────────────
    def marcar(self, activa: bool) -> None:
        self.setProperty("activa", "true" if activa else "false")
        self.lbl_check.setVisible(activa)
        self.lbl_num.setProperty("rol", "ok" if activa else "cuerpo")
        repolish(self.lbl_num)
        repolish(self)

    # ── Interacción ────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.clicada.emit(self.num_pagina, event.modifiers())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.ampliada.emit(self.num_pagina)
        super().mouseDoubleClickEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.enfocada.emit(self.num_pagina)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.ampliada.emit(self.num_pagina)
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicada.emit(self.num_pagina, Qt.KeyboardModifier.NoModifier)
            return
        super().keyPressEvent(event)


# ─────────────────────────────────────────────────────────────
#  Vista principal — Fase 1
# ─────────────────────────────────────────────────────────────
class VistaPrevisualizacion(QWidget):
    """
    Señales públicas:
      paginas_seleccionadas(list)  →  índices 0-based elegidos
      cancelar()                   →  usuario sale sin seleccionar
    """

    paginas_seleccionadas = pyqtSignal(list)
    cancelar              = pyqtSignal()

    def __init__(self, ruta_pdf: str, seleccion_inicial=None, parent=None):
        super().__init__(parent)
        # Ventana propia aunque tenga parent (si no, Qt la dibujaría
        # como widget hijo encima de la ventana principal).
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setObjectName("pantalla")
        self.setMinimumSize(520, 420)

        self.ruta_pdf = ruta_pdf
        self.tarjetas: list[TarjetaPagina] = []
        self._seleccion: set[int] = set(seleccion_inicial or ())
        self._ancla: int | None = None          # para shift+clic
        self._foco: int = 0
        self._worker: RenderWorker | None = None
        self._total_paginas = 0
        self._renderizadas = 0
        self._cols = 0
        self._ancho_tarjeta = THUMB_W_MAX
        self._dpr = float(self.devicePixelRatioF() or 1.0)

        # Debounce del reflow: redimensionar dispara muchos eventos y
        # reacomodar el grid en cada uno hace saltar la ventana.
        self._timer_reflow = QTimer(self)
        self._timer_reflow.setSingleShot(True)
        self._timer_reflow.setInterval(60)
        self._timer_reflow.timeout.connect(self._reflow)

        self._construir_ui()
        self._registrar_atajos()
        theme_signals.changed.connect(self._on_tema_cambiado)
        self._iniciar_render()

    # ══════════════════════════════════════════
    #  Construcción de la UI
    # ══════════════════════════════════════════
    def _construir_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        # ── Cabecera ────────────────────────────────────────
        nombre = os.path.basename(self.ruta_pdf)
        self.cabecera = BarraSuperior(f"Elegí las páginas a firmar  ·  {nombre}")

        self.lbl_conteo = etiqueta("Cargando…", rol="hint")
        self.cabecera.agregar(self.lbl_conteo)

        self.btn_cancelar = boton("✕  Cancelar", variant="ghost",
                                  tooltip="Cerrar sin seleccionar (Esc)",
                                  on_click=self._on_cancelar)
        self.btn_cancelar.setProperty("danger", "true")
        repolish(self.btn_cancelar)
        self.cabecera.agregar(self.btn_cancelar)
        raiz.addWidget(self.cabecera)

        # ── Barra de selección ──────────────────────────────
        barra = QFrame()
        barra.setObjectName("cabecera")
        lay_barra = QHBoxLayout(barra)
        lay_barra.setContentsMargins(SPACE["lg"], SPACE["sm"], SPACE["lg"], SPACE["sm"])
        lay_barra.setSpacing(SPACE["sm"])

        lay_barra.addWidget(etiqueta("Páginas:", rol="hint"))
        self.input_rango = QLineEdit()
        self.input_rango.setPlaceholderText("ej: 1, 3, 5-8")
        self.input_rango.setMaximumWidth(190)
        self.input_rango.setToolTip(
            "Escribí las páginas y presioná Enter.\nAcepta listas y rangos: 1, 3, 5-8")
        self.input_rango.returnPressed.connect(self._aplicar_rango)
        lay_barra.addWidget(self.input_rango)

        lay_barra.addWidget(boton("Todas", variant="ghost",
                                  height=SIZE["btn_sm"],
                                  tooltip="Seleccionar todas (Ctrl+A)",
                                  on_click=self._seleccionar_todas))
        lay_barra.addWidget(boton("Ninguna", variant="ghost",
                                  height=SIZE["btn_sm"],
                                  tooltip="Limpiar la selección",
                                  on_click=self._limpiar_seleccion))
        lay_barra.addStretch()
        self.lbl_seleccion = etiqueta("Ninguna página seleccionada", rol="hint")
        lay_barra.addWidget(self.lbl_seleccion)
        raiz.addWidget(barra)

        # ── Área scrollable con grid ─────────────────────────
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._cont_grid = QWidget()
        self._cont_grid.setObjectName("contenidoGrid")
        self.grid = QGridLayout(self._cont_grid)
        self.grid.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"])
        self.grid.setSpacing(SPACE["md"])
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self._cont_grid)
        raiz.addWidget(self.scroll, 1)

        # ── Barra inferior ───────────────────────────────────
        self.pie = BarraInferior(
            "Clic para elegir · Shift+clic para un rango · doble clic para ampliar")
        self.btn_continuar = boton("Imprimir páginas  →",
                                   height=SIZE["btn_lg"], enabled=False,
                                   tooltip="Enviar las páginas elegidas a la impresora (Enter)",
                                   on_click=self._on_continuar)
        self.pie.agregar(self.btn_continuar)
        raiz.addWidget(self.pie)

    def _registrar_atajos(self):
        QShortcut(QKeySequence("Ctrl+A"), self, activated=self._seleccionar_todas)
        QShortcut(QKeySequence("Ctrl+F"), self,
                  activated=lambda: self.input_rango.setFocus())

    # ══════════════════════════════════════════
    #  Render de thumbnails
    # ══════════════════════════════════════════
    def _iniciar_render(self):
        if not PYMUPDF_DISPONIBLE:
            self._mostrar_error(
                "PyMuPDF no está instalado.\nEjecutá:  pip install pymupdf")
            return
        self._worker = RenderWorker(self.ruta_pdf, THUMB_W_MAX, self._dpr)
        self._worker.total_paginas.connect(self._on_total_paginas)
        self._worker.thumbnail_listo.connect(self._on_thumbnail)
        self._worker.terminado.connect(self._on_render_terminado)
        self._worker.fallo.connect(self._mostrar_error)
        self._worker.start()

    def _on_total_paginas(self, total: int):
        """Crea todas las tarjetas de una (con skeleton) apenas se sabe
        cuántas páginas hay. El grid queda estable desde el principio."""
        self._total_paginas = total
        self._ancho_tarjeta, self._cols = self._calcular_metricas(total)

        # Una selección heredada puede venir de un PDF más largo
        self._seleccion = {p for p in self._seleccion if 0 <= p < total}

        for i in range(total):
            t = TarjetaPagina(i, self._ancho_tarjeta)
            t.clicada.connect(self._on_click_tarjeta)
            t.ampliada.connect(self._abrir_vista_grande)
            t.enfocada.connect(self._on_foco_tarjeta)
            self.tarjetas.append(t)

        self._colocar_en_grid()
        self._sincronizar_marcas()
        self._actualizar_conteo()
        if self.tarjetas:
            self.tarjetas[0].setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_thumbnail(self, num: int, imagen: QImage):
        if 0 <= num < len(self.tarjetas):
            self.tarjetas[num].set_imagen(imagen, self._dpr)
            self._renderizadas += 1
            self._actualizar_conteo()

    def _on_render_terminado(self, _total: int):
        self._actualizar_conteo(final=True)

    def _actualizar_conteo(self, final: bool = False):
        total = self._total_paginas
        if total <= 0:
            self.lbl_conteo.setText("Sin páginas")
            return
        s = "s" if total != 1 else ""
        if final or self._renderizadas >= total:
            self.lbl_conteo.setText(f"{total} página{s}")
        else:
            self.lbl_conteo.setText(f"{self._renderizadas}/{total} página{s}…")

    def _mostrar_error(self, mensaje: str):
        self.lbl_conteo.setText("Error")
        lbl = etiqueta(f"⚠  {mensaje}", rol="error", wrap=True,
                       align=Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(lbl, 0, 0)

    # ══════════════════════════════════════════
    #  Layout responsive
    # ══════════════════════════════════════════
    def _ancho_util(self) -> int:
        """Ancho disponible para las tarjetas.

        Se mide sobre el QScrollArea y NO sobre su viewport: como las
        tarjetas tienen ancho fijo, el viewport no puede achicarse por
        debajo del ancho mínimo del grid, así que al angostar la ventana
        devolvía un valor inflado y el grid nunca reflotaba a menos
        columnas. El ancho del scroll sí sigue al de la ventana.
        """
        margenes = self.grid.contentsMargins()
        reserva_scrollbar = 12
        return max(
            THUMB_W_MIN,
            self.scroll.width() - margenes.left() - margenes.right() - reserva_scrollbar,
        )

    def _calcular_metricas(self, total: int | None = None) -> tuple[int, int]:
        """Devuelve (ancho_tarjeta, columnas) para el ancho disponible."""
        total = self._total_paginas if total is None else total
        disp = self._ancho_util()
        gap = self.grid.spacing()

        cols = max(1, (disp + gap) // (THUMB_W_MIN + gap))
        if total:
            cols = min(cols, max(1, total))
        ancho = (disp - gap * (cols - 1)) // cols
        ancho = max(THUMB_W_MIN, min(THUMB_W_MAX, int(ancho)))
        return ancho, int(cols)

    def _colocar_en_grid(self):
        while self.grid.count():
            self.grid.takeAt(0)
        for i, t in enumerate(self.tarjetas):
            self.grid.addWidget(t, i // self._cols, i % self._cols,
                                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        # Columna elástica al final: las tarjetas quedan pegadas a la
        # izquierda en vez de estirarse de forma despareja.
        for c in range(self._cols):
            self.grid.setColumnStretch(c, 0)
        self.grid.setColumnStretch(self._cols, 1)

    def _reflow(self):
        if not self.tarjetas:
            return
        ancho, cols = self._calcular_metricas()
        if ancho != self._ancho_tarjeta:
            self._ancho_tarjeta = ancho
            for t in self.tarjetas:
                t.set_ancho(ancho)
        if cols != self._cols:
            self._cols = cols
            self._colocar_en_grid()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._timer_reflow.start()

    def _on_tema_cambiado(self, _modo: str):
        # Repinta los skeletons de las tarjetas que aún no tienen render.
        for t in self.tarjetas:
            t.set_ancho(t._ancho)

    # ══════════════════════════════════════════
    #  Selección
    # ══════════════════════════════════════════
    def _on_foco_tarjeta(self, num: int):
        self._foco = num

    def _on_click_tarjeta(self, num: int, modificadores):
        """Alterna la página, o selecciona un rango con Shift."""
        shift = bool(modificadores & Qt.KeyboardModifier.ShiftModifier)
        if shift and self._ancla is not None:
            desde, hasta = sorted((self._ancla, num))
            self._seleccion.update(range(desde, hasta + 1))
        else:
            if num in self._seleccion:
                self._seleccion.discard(num)
            else:
                self._seleccion.add(num)
            self._ancla = num
        self._sincronizar_marcas()

    def _seleccionar_todas(self):
        self._seleccion = set(range(len(self.tarjetas)))
        self._ancla = 0
        self._sincronizar_marcas()

    def _limpiar_seleccion(self):
        self._seleccion.clear()
        self._ancla = None
        self._sincronizar_marcas()

    def _aplicar_rango(self):
        texto = self.input_rango.text().strip()
        if not texto:
            return
        paginas = parsear_paginas(texto, self._total_paginas)
        if not paginas:
            self.pie.set_estado(
                f"No se entendió «{texto}». Probá con algo como  1, 3, 5-8",
                rol="error")
            return
        self._seleccion = set(paginas)
        self._ancla = paginas[0]
        self._sincronizar_marcas()
        if self.tarjetas:
            self.scroll.ensureWidgetVisible(self.tarjetas[paginas[0]])

    def _sincronizar_marcas(self):
        """Refleja el estado de la selección en tarjetas, contador y botón."""
        for t in self.tarjetas:
            t.marcar(t.num_pagina in self._seleccion)

        cantidad = len(self._seleccion)
        self.btn_continuar.setEnabled(cantidad > 0)
        if cantidad:
            plural = "s" if cantidad != 1 else ""
            self.lbl_seleccion.setText(
                f"{cantidad} página{plural}: {formatear_paginas(sorted(self._seleccion))}")
            self.lbl_seleccion.setProperty("rol", "ok")
            self.btn_continuar.setText(
                f"Imprimir {cantidad} página{plural}  →")
            self.pie.set_estado(
                f"✔  {formatear_paginas(sorted(self._seleccion))} "
                f"— listas para imprimir", rol="ok")
        else:
            self.lbl_seleccion.setText("Ninguna página seleccionada")
            self.lbl_seleccion.setProperty("rol", "hint")
            self.btn_continuar.setText("Imprimir páginas  →")
            self.pie.set_estado(
                "Clic para elegir · Shift+clic para un rango · doble clic para ampliar")
        repolish(self.lbl_seleccion)

    # ══════════════════════════════════════════
    #  Vista previa grande
    # ══════════════════════════════════════════
    def _abrir_vista_grande(self, num: int):
        dlg = DialogoVistaPagina(self.ruta_pdf, num, self._total_paginas,
                                 self._seleccion, parent=self)
        dlg.seleccion_cambiada.connect(self._on_seleccion_desde_vista)
        dlg.exec()

    def _on_seleccion_desde_vista(self, pagina: int, activa: bool):
        if activa:
            self._seleccion.add(pagina)
        else:
            self._seleccion.discard(pagina)
        self._ancla = pagina
        self._sincronizar_marcas()

    # ══════════════════════════════════════════
    #  Salida
    # ══════════════════════════════════════════
    def _on_continuar(self):
        if self._seleccion:
            self.paginas_seleccionadas.emit(sorted(self._seleccion))

    def _on_cancelar(self):
        self._detener_worker()
        self.cancelar.emit()

    def keyPressEvent(self, event):
        tecla = event.key()
        if tecla == Qt.Key.Key_Escape:
            self._on_cancelar()
            return
        if tecla in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.btn_continuar.isEnabled():
            self._on_continuar()
            return
        if self.tarjetas and tecla in (
            Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up,
            Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End,
        ):
            destino = {
                Qt.Key.Key_Left:  self._foco - 1,
                Qt.Key.Key_Right: self._foco + 1,
                Qt.Key.Key_Up:    self._foco - self._cols,
                Qt.Key.Key_Down:  self._foco + self._cols,
                Qt.Key.Key_Home:  0,
                Qt.Key.Key_End:   len(self.tarjetas) - 1,
            }[tecla]
            destino = max(0, min(len(self.tarjetas) - 1, destino))
            self.tarjetas[destino].setFocus(Qt.FocusReason.TabFocusReason)
            self.scroll.ensureWidgetVisible(self.tarjetas[destino])
            return
        super().keyPressEvent(event)

    # ══════════════════════════════════════════
    #  Ciclo de vida
    # ══════════════════════════════════════════
    def _detener_worker(self):
        if self._worker is not None:
            if self._worker.isRunning():
                self._worker.cancelar()
                if not self._worker.wait(3000):
                    self._worker.terminate()
                    self._worker.wait(500)
            self._worker.deleteLater()
            self._worker = None

    def closeEvent(self, event):
        self._detener_worker()
        try:
            theme_signals.changed.disconnect(self._on_tema_cambiado)
        except (TypeError, RuntimeError):
            pass
        super().closeEvent(event)
