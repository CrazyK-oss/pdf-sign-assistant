"""
modules/ui.py
============================================================
Kit de componentes compartidos.

Todas las pantallas (fases 1-4, ajustes, ventana principal) construyen
su UI con estas funciones para que el resultado sea idéntico en forma,
espaciado y comportamiento. Nada de estilos inline por módulo: los
colores y tamaños salen siempre de modules.theme.

Contenido:
  - boton()          botón con variantes estandarizadas
  - etiqueta()       QLabel con rol semántico (titulo/hint/error/…)
  - separador()      línea divisoria horizontal
  - tarjeta()        contenedor QFrame con padding y layout listo
  - BarraSuperior    cabecera común de las ventanas de fase
  - BarraInferior    pie con estado + acción principal
  - FilaAdaptable    fila que se apila en vertical en ventanas angostas
  - AreaScroll       scroll vertical con el contenido dentro
  - abrir_en_sistema()  abre carpetas/URIs en el explorador o navegador
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from modules.theme import BREAKPOINT, SIZE, SPACE, repolish

# Variantes de botón admitidas (deben existir en el QSS de theme.py)
VARIANTES = ("primary", "secondary", "ghost", "danger", "success")


# ── Controles básicos ─────────────────────────────────────────────────────────

def boton(
    texto: str,
    *,
    variant: str = "primary",
    tooltip: str = "",
    min_w: int = 0,
    fixed_w: int = 0,
    height: int = SIZE["btn"],
    on_click=None,
    enabled: bool = True,
    compacto: bool = False,
) -> QPushButton:
    """Crea un QPushButton estandarizado.

    variant:  primary | secondary | ghost | danger | success
    compacto: reduce el padding, para botones angostos cuyo texto no
              entraría con el padding normal (ej: "+90°").
    """
    if variant not in VARIANTES:
        variant = "primary"
    b = QPushButton(texto)
    b.setProperty("variant", variant)
    if compacto:
        b.setProperty("compacto", "true")
    b.setMinimumHeight(height)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if fixed_w:
        b.setFixedWidth(fixed_w)
    elif min_w:
        b.setMinimumWidth(min_w)
    if tooltip:
        b.setToolTip(tooltip)
    if on_click is not None:
        b.clicked.connect(on_click)
    b.setEnabled(enabled)
    repolish(b)
    return b


def etiqueta(
    texto: str = "",
    *,
    rol: str = "cuerpo",
    wrap: bool = False,
    align: Qt.AlignmentFlag | None = None,
) -> QLabel:
    """QLabel con un rol semántico definido en el tema.

    rol: titulo | tituloBarra | subtitulo | seccion | cuerpo | hint
         | ok | error | badge
    """
    lbl = QLabel(texto)
    lbl.setProperty("rol", rol)
    if wrap:
        lbl.setWordWrap(True)
    if align is not None:
        lbl.setAlignment(align)
    repolish(lbl)
    return lbl


def separador() -> QFrame:
    s = QFrame()
    s.setFrameShape(QFrame.Shape.HLine)
    s.setFrameShadow(QFrame.Shadow.Plain)
    s.setFixedHeight(1)
    return s


def tarjeta(*, acento: bool = False, padding: int = SPACE["lg"],
            spacing: int = SPACE["sm"]) -> tuple[QFrame, QVBoxLayout]:
    """Devuelve (frame, layout) de una tarjeta con padding estándar."""
    f = QFrame()
    f.setObjectName("cardAcento" if acento else "card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(padding, padding, padding, padding)
    lay.setSpacing(spacing)
    return f, lay


def expansor_h() -> QWidget:
    """Espaciador elástico horizontal (equivalente a addStretch)."""
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return w


# ── Barras de ventana ─────────────────────────────────────────────────────────

class BarraSuperior(QFrame):
    """Cabecera común de las ventanas de fase: título + acciones a la derecha.

    Usa alto MÍNIMO (no fijo) para tolerar escalado de fuente y DPI alto.
    """

    def __init__(self, titulo: str, parent=None):
        super().__init__(parent)
        self.setObjectName("cabecera")
        self.setMinimumHeight(SIZE["bar"])
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(SPACE["lg"], SPACE["sm"], SPACE["lg"], SPACE["sm"])
        self._lay.setSpacing(SPACE["md"])

        self.lbl_titulo = etiqueta(titulo, rol="tituloBarra")
        self.lbl_titulo.setSizePolicy(QSizePolicy.Policy.Ignored,
                                      QSizePolicy.Policy.Preferred)
        self.lbl_titulo.setToolTip(titulo)
        self._lay.addWidget(self.lbl_titulo, 1)

    def set_titulo(self, texto: str) -> None:
        self.lbl_titulo.setText(texto)
        self.lbl_titulo.setToolTip(texto)

    def agregar(self, widget: QWidget) -> QWidget:
        self._lay.addWidget(widget, 0)
        return widget


class BarraInferior(QFrame):
    """Pie de ventana: mensaje de estado a la izquierda, acción principal
    a la derecha. En ventanas angostas el mensaje se elide en vez de
    empujar el botón fuera de la pantalla."""

    def __init__(self, mensaje: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("barraInferior")
        self.setMinimumHeight(SIZE["bar"])
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(SPACE["lg"], SPACE["sm"], SPACE["lg"], SPACE["sm"])
        self._lay.setSpacing(SPACE["md"])

        self.lbl_estado = etiqueta(mensaje, rol="cuerpo")
        self.lbl_estado.setSizePolicy(QSizePolicy.Policy.Ignored,
                                      QSizePolicy.Policy.Preferred)
        self._lay.addWidget(self.lbl_estado, 1)

    def set_estado(self, texto: str, *, rol: str = "cuerpo") -> None:
        self.lbl_estado.setText(texto)
        self.lbl_estado.setProperty("rol", rol)
        self.lbl_estado.setToolTip(texto)
        repolish(self.lbl_estado)

    def agregar(self, widget: QWidget) -> QWidget:
        self._lay.addWidget(widget, 0)
        return widget


# ── Contenedores responsive ───────────────────────────────────────────────────

class FilaAdaptable(QWidget):
    """Fila horizontal que se convierte en columna cuando el ancho
    disponible baja del punto de corte.

    Es la pieza que hace responsive a las pantallas con dos paneles
    lado a lado (fase 3) o filas de botones (ventana principal).
    """

    orientacion_cambiada = pyqtSignal(bool)   # True = apilado en vertical

    def __init__(self, *, breakpoint_px: int = BREAKPOINT["md"],
                 spacing: int = SPACE["md"], parent=None):
        super().__init__(parent)
        self._breakpoint = breakpoint_px
        self._apilado = False
        self._lay = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(spacing)

    def agregar(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._lay.addWidget(widget, stretch)
        return widget

    def agregar_stretch(self, stretch: int = 1) -> None:
        self._lay.addStretch(stretch)

    @property
    def apilado(self) -> bool:
        return self._apilado

    def resizeEvent(self, event):
        super().resizeEvent(event)
        apilar = self.width() < self._breakpoint
        if apilar != self._apilado:
            self._apilado = apilar
            self._lay.setDirection(
                QBoxLayout.Direction.TopToBottom if apilar
                else QBoxLayout.Direction.LeftToRight
            )
            self.orientacion_cambiada.emit(apilar)


class AreaScroll(QScrollArea):
    """Scroll vertical con un contenedor listo para usar.

    Evita que las pantallas se recorten en monitores bajos o con
    escalado de fuente grande: el contenido siempre es alcanzable.
    """

    def __init__(self, *, margenes: tuple[int, int, int, int] | None = None,
                 spacing: int = SPACE["lg"], parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.contenido = QWidget()
        self.contenido.setObjectName("contenidoScroll")
        m = margenes or (SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"])
        self.lay = QVBoxLayout(self.contenido)
        self.lay.setContentsMargins(*m)
        self.lay.setSpacing(spacing)
        self.setWidget(self.contenido)


# ── Utilidades de sistema ─────────────────────────────────────────────────────

def abrir_en_sistema(destino: str | Path) -> None:
    """Abre una carpeta, archivo o URI con la aplicación predeterminada.

    Centraliza el 'if win32 / darwin / else' que estaba duplicado en
    main.py y fase4_email.py.
    """
    destino = str(destino)
    if sys.platform == "win32":
        os.startfile(destino)          # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", destino])
    else:
        subprocess.Popen(["xdg-open", destino])


def elide(texto: str, maximo: int = 60) -> str:
    """Acorta un texto largo por el medio (útil para rutas)."""
    if len(texto) <= maximo:
        return texto
    mitad = (maximo - 1) // 2
    return f"{texto[:mitad]}…{texto[-mitad:]}"
