"""
modules/fase1_preview.py
============================================================
Fase 1: grid de páginas del PDF para seleccionar cuál se imprime.

Puntos clave de esta versión
----------------------------
* THREAD-SAFETY: el worker emite QImage, no QPixmap. Qt sólo permite
  construir QPixmap en el hilo de GUI; hacerlo en un QThread era un
  crash latente (y en algunas máquinas, un crash real).
* Las tarjetas se crean una sola vez, apenas se conoce el total de
  páginas, y se rellenan a medida que llegan los renders. Antes se
  creaban dentro del callback y el número de columnas se recalculaba
  en cada llegada: si la ventana cambiaba de tamaño a mitad de carga,
  el grid quedaba con huecos y tarjetas superpuestas.
* Grid responsive real: las columnas y el ancho de tarjeta se recalculan
  al redimensionar (con debounce) sin volver a renderizar el PDF.
* Estilos 100% del tema (soporta modo oscuro y cambio en caliente).
* Navegación por teclado: flechas, Home/End, Enter y Esc.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules.theme import (
    SIZE,
    SPACE,
    THEME,
    repolish,
    theme_signals,
)
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
#  Tarjeta individual de página
# ─────────────────────────────────────────────────────────────
class TarjetaPagina(QFrame):
    """Tarjeta clicable de una página. Sin estilos propios: todo el
    aspecto (normal / hover / activa / foco) sale del QSS del tema."""

    seleccionada = pyqtSignal(int)
    confirmada   = pyqtSignal(int)   # doble clic → seguir de una

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

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE["sm"], SPACE["sm"], SPACE["sm"], SPACE["xs"])
        lay.setSpacing(SPACE["xs"])

        self.lbl_img = QLabel()
        self.lbl_img.setObjectName("lienzoPagina")
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_img.setScaledContents(False)
        lay.addWidget(self.lbl_img)

        self.lbl_num = etiqueta(f"Página {num_pagina + 1}", rol="cuerpo",
                                align=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_num)

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
        escalado = self._pixmap_fuente.scaled(
            ancho_img * int(self._pixmap_fuente.devicePixelRatio() or 1),
            alto_img * int(self._pixmap_fuente.devicePixelRatio() or 1),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        escalado.setDevicePixelRatio(self._pixmap_fuente.devicePixelRatio())
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
        self.lbl_num.setProperty("rol", "ok" if activa else "cuerpo")
        repolish(self.lbl_num)
        repolish(self)

    # ── Interacción ────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.seleccionada.emit(self.num_pagina)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.confirmada.emit(self.num_pagina)
        super().mouseDoubleClickEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.seleccionada.emit(self.num_pagina)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.confirmada.emit(self.num_pagina)
            return
        super().keyPressEvent(event)


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

    def __init__(self, ruta_pdf: str, parent=None):
        super().__init__(parent)
        # Ventana propia aunque tenga parent (si no, Qt la dibujaría
        # como widget hijo encima de la ventana principal).
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setObjectName("pantalla")
        self.setMinimumSize(520, 420)

        self.ruta_pdf = ruta_pdf
        self.tarjetas: list[TarjetaPagina] = []
        self._pagina_activa: int | None = None
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
        self.cabecera = BarraSuperior(f"Seleccioná una página  ·  {nombre}")

        self.lbl_conteo = etiqueta("Cargando…", rol="hint")
        self.cabecera.agregar(self.lbl_conteo)

        self.btn_cancelar = boton("✕  Cancelar", variant="ghost",
                                  tooltip="Cerrar sin seleccionar (Esc)",
                                  on_click=self._on_cancelar)
        self.btn_cancelar.setProperty("danger", "true")
        repolish(self.btn_cancelar)
        self.cabecera.agregar(self.btn_cancelar)
        raiz.addWidget(self.cabecera)

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
        self.pie = BarraInferior("Hacé clic en una página para seleccionarla")
        self.btn_continuar = boton("Imprimir página seleccionada  →",
                                   height=SIZE["btn_lg"], enabled=False,
                                   tooltip="Enviar la página elegida a la impresora (Enter)",
                                   on_click=self._on_continuar)
        self.pie.agregar(self.btn_continuar)
        raiz.addWidget(self.pie)

    # ══════════════════════════════════════════
    #  Render de thumbnails
    # ══════════════════════════════════════════
    def _iniciar_render(self):
        if not PYMUPDF_DISPONIBLE:
            self._mostrar_error(
                "PyMuPDF no está instalado.\nEjecutá:  pip install pymupdf"
            )
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

        for i in range(total):
            t = TarjetaPagina(i, self._ancho_tarjeta)
            t.seleccionada.connect(self._on_tarjeta_click)
            t.confirmada.connect(self._on_tarjeta_confirmada)
            self.tarjetas.append(t)

        self._colocar_en_grid()
        self._actualizar_conteo()
        if self.tarjetas:
            self.tarjetas[0].setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_thumbnail(self, num: int, imagen: QImage):
        if 0 <= num < len(self.tarjetas):
            self.tarjetas[num].set_imagen(imagen, self._dpr)
            self._renderizadas += 1
            self._actualizar_conteo()

    def _on_render_terminado(self, total: int):
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
    #  Interacción
    # ══════════════════════════════════════════
    def _on_tarjeta_click(self, num: int):
        if self._pagina_activa == num:
            return
        if self._pagina_activa is not None and 0 <= self._pagina_activa < len(self.tarjetas):
            self.tarjetas[self._pagina_activa].marcar(False)

        self._pagina_activa = num
        self.tarjetas[num].marcar(True)
        self.pie.set_estado(
            f"✔  Página {num + 1} seleccionada  ·  lista para imprimir", rol="ok"
        )
        self.btn_continuar.setEnabled(True)

    def _on_tarjeta_confirmada(self, num: int):
        self._on_tarjeta_click(num)
        self._on_continuar()

    def _on_continuar(self):
        if self._pagina_activa is not None:
            self.pagina_seleccionada.emit(self._pagina_activa)

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
            actual = self._pagina_activa if self._pagina_activa is not None else 0
            destino = {
                Qt.Key.Key_Left:  actual - 1,
                Qt.Key.Key_Right: actual + 1,
                Qt.Key.Key_Up:    actual - self._cols,
                Qt.Key.Key_Down:  actual + self._cols,
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
