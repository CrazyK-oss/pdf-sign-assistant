"""
modules/ui.py
============================================================
Kit de componentes compartidos.

Todas las pantallas (fases 1-4, herramientas, ajustes, ventana principal)
construyen su UI con estas funciones para que el resultado sea idéntico
en forma, espaciado y comportamiento. Nada de estilos inline por módulo:
los colores y tamaños salen siempre de modules.theme, y los iconos de
modules.iconos.

Contenido:
  - boton()             botón con variantes e icono opcional
  - boton_icono()       botón cuadrado de sólo icono
  - etiqueta()          QLabel con rol semántico (titulo/hint/error/…)
  - icono_label()       QLabel que muestra un icono y sigue al tema
  - Chip                píldora de estado (icono + texto corto)
  - Aviso               franja informativa en línea
  - TarjetaHerramienta  tarjeta clicable del menú de herramientas
  - separador()         línea divisoria horizontal
  - tarjeta()           contenedor QFrame con padding y layout listo
  - sombra()            elevación (QSS no tiene box-shadow)
  - BarraSuperior       cabecera común de las ventanas de fase
  - BarraInferior       pie con estado + acción principal
  - FilaAdaptable       fila que se apila en vertical en ventanas angostas
  - AreaScroll          scroll vertical con el contenido dentro
  - Buscador            QLineEdit con la lupa dibujada adentro
  - abrir_en_sistema()  abre carpetas/URIs en el explorador o navegador
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from modules import iconos
from modules.theme import (
    BREAKPOINT,
    FS,
    SIZE,
    SPACE,
    THEME,
    repolish,
    theme_signals,
)

# Variantes de botón admitidas (deben existir en el QSS de theme.py)
VARIANTES = ("primary", "secondary", "ghost", "danger", "success", "nav", "plano")

# Color del icono según la variante y el estado del botón.
#   variante → (normal, hover, marcado)
# Las variantes cuyo texto se invierte al pasar el mouse (secondary sobre
# fondo lleno, ghost que se aclara) necesitan que el icono acompañe: si no,
# queda teal sobre teal y desaparece.
_COLOR_ICONO = {
    "primary":   ("on_primary", "on_primary", "on_primary"),
    "danger":    ("on_danger",  "on_danger",  "on_danger"),
    "success":   ("on_success", "on_success", "on_success"),
    "secondary": ("primary",    "on_primary", "on_primary"),
    "ghost":     ("text_muted", "text",       "primary"),
    "nav":       ("text_muted", "text",       "primary"),
    "plano":     ("text_muted", "text",       "primary"),
}


# ── Controles básicos ─────────────────────────────────────────────────────────

class BotonIcono(QPushButton):
    """Botón cuyo icono se recolorea solo.

    El icono es un pixmap con el color quemado adentro, así que hay que
    volver a generarlo cuando cambia algo que afecte al color: el hover,
    el estado marcado, si se deshabilita, o el tema entero. Este botón se
    encarga de todo eso; desde afuera se usa como un QPushButton normal.
    """

    def __init__(self, texto: str = "", *, nombre_icono: str = "",
                 variant: str = "primary", tamano_icono: int = SIZE["icono"],
                 parent=None):
        super().__init__(texto, parent)
        self._nombre_icono = nombre_icono
        self._variant = variant if variant in VARIANTES else "primary"
        self._tamano_icono = tamano_icono
        self._hover = False
        self.setProperty("variant", self._variant)
        self.setIconSize(QSize(tamano_icono, tamano_icono))
        # Se desconecta sola cuando se destruye el botón (PyQt ata la
        # conexión al ciclo de vida del receptor QObject).
        theme_signals.changed.connect(self._al_cambiar_tema)
        self._refrescar_icono()

    # -- estado --------------------------------------------------------------
    def set_nombre_icono(self, nombre: str) -> None:
        self._nombre_icono = nombre
        self._refrescar_icono()

    def nombre_icono(self) -> str:
        return self._nombre_icono

    def set_variant(self, variant: str) -> None:
        """Cambia la variante en caliente (por ejemplo, primary → danger).

        Hay que pasar por acá y no setear la propiedad a mano: el color
        del icono se elige por variante, y tocando sólo el QSS quedaría
        con el color de la variante anterior.
        """
        if variant not in VARIANTES:
            variant = "primary"
        self._variant = variant
        self.setProperty("variant", variant)
        repolish(self)
        self._refrescar_icono()

    def _token_color(self) -> str:
        normal, hover, marcado = _COLOR_ICONO.get(
            self._variant, _COLOR_ICONO["primary"])
        if not self.isEnabled():
            return "text_faint"
        if self.isCheckable() and self.isChecked():
            return marcado
        if self._hover:
            # El ghost "peligroso" invierte a fondo rojo con texto blanco.
            if self._variant == "ghost" and self.property("danger") == "true":
                return "on_danger"
            return hover
        if self._variant == "ghost" and self.property("danger") == "true":
            return "danger"
        return normal

    def _refrescar_icono(self) -> None:
        if not self._nombre_icono:
            return
        self.setIcon(iconos.icono(self._nombre_icono, self._tamano_icono,
                                  color=self._token_color()))

    # -- eventos que cambian el color ---------------------------------------
    def _al_cambiar_tema(self, _modo: str) -> None:
        self._refrescar_icono()

    def enterEvent(self, event):
        self._hover = True
        self._refrescar_icono()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._refrescar_icono()
        super().leaveEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.EnabledChange, QEvent.Type.PaletteChange):
            self._refrescar_icono()

    def setChecked(self, marcado: bool) -> None:      # noqa: N802 (API de Qt)
        super().setChecked(marcado)
        self._refrescar_icono()

    def nextCheckState(self):                          # noqa: N802 (API de Qt)
        super().nextCheckState()
        self._refrescar_icono()


def boton(
    texto: str = "",
    *,
    variant: str = "primary",
    icono: str = "",
    tooltip: str = "",
    min_w: int = 0,
    fixed_w: int = 0,
    height: int = SIZE["btn"],
    on_click=None,
    enabled: bool = True,
    compacto: bool = False,
    checkable: bool = False,
    tamano_icono: int = SIZE["icono"],
) -> QPushButton:
    """Crea un QPushButton estandarizado.

    variant:  primary | secondary | ghost | danger | success | nav | plano
    icono:    nombre del catálogo de modules.iconos (ver iconos.nombres())
    compacto: reduce el padding, para botones angostos cuyo texto no
              entraría con el padding normal (ej: "+90°").
    """
    if variant not in VARIANTES:
        variant = "primary"
    b = BotonIcono(texto, nombre_icono=icono, variant=variant,
                   tamano_icono=tamano_icono)
    if compacto:
        b.setProperty("compacto", "true")
    b.setMinimumHeight(height)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if checkable:
        b.setCheckable(True)
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


def boton_icono(
    nombre: str,
    *,
    tooltip: str = "",
    variant: str = "ghost",
    lado: int = SIZE["btn"],
    tamano_icono: int = SIZE["icono"],
    on_click=None,
    enabled: bool = True,
    checkable: bool = False,
) -> QPushButton:
    """Botón cuadrado de sólo icono (barra superior, acciones de fila…).

    El tooltip no es decorativo: es la única etiqueta que tiene el botón,
    así que conviene que diga qué hace.
    """
    b = BotonIcono("", nombre_icono=nombre, variant=variant,
                   tamano_icono=tamano_icono)
    b.setProperty("soloicono", "true")
    b.setFixedSize(lado, lado)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if checkable:
        b.setCheckable(True)
    if tooltip:
        b.setToolTip(tooltip)
        b.setAccessibleName(tooltip)
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

    rol: display | titulo | tituloBarra | subtitulo | seccion | cuerpo
         | hint | ok | error | badge
    """
    lbl = QLabel(texto)
    lbl.setProperty("rol", rol)
    if wrap:
        lbl.setWordWrap(True)
    if align is not None:
        lbl.setAlignment(align)
    repolish(lbl)
    return lbl


class IconoLabel(QLabel):
    """QLabel que muestra un icono del catálogo y se repinta con el tema."""

    def __init__(self, nombre: str, tamano: int = SIZE["icono"], *,
                 color: str = "text_muted", parent=None):
        super().__init__(parent)
        self._nombre = nombre
        self._tamano = tamano
        self._color = color
        self.setFixedSize(tamano, tamano)
        self.setScaledContents(False)
        theme_signals.changed.connect(self._al_cambiar_tema)
        self._refrescar()

    def set_icono(self, nombre: str, *, color: str | None = None) -> None:
        self._nombre = nombre
        if color is not None:
            self._color = color
        self._refrescar()

    def set_color(self, color: str) -> None:
        self._color = color
        self._refrescar()

    def _refrescar(self) -> None:
        self.setPixmap(iconos.pixmap(self._nombre, self._tamano,
                                     color=self._color))

    def _al_cambiar_tema(self, _modo: str) -> None:
        self._refrescar()


def icono_label(nombre: str, tamano: int = SIZE["icono"], *,
                color: str = "text_muted") -> IconoLabel:
    return IconoLabel(nombre, tamano, color=color)


def selector(opciones, *, actual: str = "", on_change=None,
             min_w: int = 0, tooltips: dict | None = None) -> QComboBox:
    """QComboBox estandarizado a partir de pares (clave, texto).

    La clave viaja en el UserRole, así que el código nunca compara por el
    texto visible: renombrar una opción no rompe la lógica.
    """
    c = QComboBox()
    c.setMinimumHeight(SIZE["input"])
    if min_w:
        c.setMinimumWidth(min_w)
    for clave, texto in opciones:
        c.addItem(texto, clave)
        if tooltips and clave in tooltips:
            c.setItemData(c.count() - 1, tooltips[clave],
                          Qt.ItemDataRole.ToolTipRole)
    if actual:
        i = c.findData(actual)
        if i >= 0:
            c.setCurrentIndex(i)
    if on_change is not None:
        c.currentIndexChanged.connect(lambda _i: on_change(c.currentData()))
    return c


def separador() -> QFrame:
    s = QFrame()
    s.setFrameShape(QFrame.Shape.HLine)
    s.setFrameShadow(QFrame.Shadow.Plain)
    s.setFixedHeight(1)
    return s


def separador_v(alto: int = 24) -> QFrame:
    s = QFrame()
    s.setObjectName("separadorV")
    s.setFixedWidth(1)
    s.setFixedHeight(alto)
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


# ── Elevación ─────────────────────────────────────────────────────────────────

_RGBA = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)")


def _a_color(valor: str) -> QColor:
    """Convierte '#rrggbb' o 'rgba(r,g,b,a)' en QColor."""
    m = _RGBA.match(valor.strip())
    if m:
        r, g, b, a = m.groups()
        c = QColor(int(r), int(g), int(b))
        c.setAlphaF(float(a) if a is not None else 1.0)
        return c
    return QColor(valor)


def sombra(widget: QWidget, *, desenfoque: int = 20, dy: int = 3) -> QWidget:
    """Aplica elevación a un widget.

    QSS no tiene box-shadow, así que la profundidad se consigue con un
    efecto gráfico. Ojo: el layout que contiene al widget tiene que dejar
    margen, o la sombra queda recortada contra el borde.
    """
    efecto = QGraphicsDropShadowEffect(widget)
    efecto.setBlurRadius(desenfoque)
    efecto.setOffset(0, dy)
    efecto.setColor(_a_color(THEME.get("shadow", "rgba(0,0,0,0.15)")))
    widget.setGraphicsEffect(efecto)
    return widget


# ── Chips y avisos ────────────────────────────────────────────────────────────

#: tono → (nombre de icono por defecto, token de color)
TONOS = {
    "neutro":  ("info",          "text_muted"),
    "ok":      ("check-circulo", "success"),
    "warn":    ("alerta",        "warning"),
    "err":     ("error-circulo", "danger"),
    "info":    ("info",          "info"),
    "primary": ("chispa",        "primary"),
}


class Chip(QFrame):
    """Píldora chica: icono + texto. Para estados que se leen de un vistazo
    ("3 páginas", "Escáner listo", "Sin conexión")."""

    def __init__(self, texto: str = "", *, tono: str = "neutro",
                 icono_nombre: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("chip")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE["sm"], 4, SPACE["sm"], 4)
        lay.setSpacing(SPACE["xs"] + 2)

        self._icono = IconoLabel("info", 13, color="text_muted")
        self._texto = QLabel(texto)
        lay.addWidget(self._icono)
        lay.addWidget(self._texto)

        self.set_tono(tono, icono_nombre)

    def set_texto(self, texto: str) -> None:
        self._texto.setText(texto)

    def set_tono(self, tono: str, icono_nombre: str | None = None) -> None:
        if tono not in TONOS:
            tono = "neutro"
        nombre, token = TONOS[tono]
        self.setProperty("tono", tono)
        self._icono.set_icono(icono_nombre or nombre, color=token)
        repolish(self)

    def set_estado(self, texto: str, tono: str = "neutro",
                   icono_nombre: str | None = None) -> None:
        self.set_texto(texto)
        self.set_tono(tono, icono_nombre)


class Aviso(QFrame):
    """Franja informativa en línea: icono + mensaje, con tono de color.

    Reemplaza a los mensajes que antes empezaban con 💡 / ⚠️ / ❌ y que
    dependían de que la fuente tuviera el emoji.
    """

    def __init__(self, texto: str = "", *, tono: str = "info",
                 icono_nombre: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("aviso")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE["md"], SPACE["sm"] + 2,
                               SPACE["md"], SPACE["sm"] + 2)
        lay.setSpacing(SPACE["sm"] + 2)

        self._icono = IconoLabel("info", SIZE["icono"], color="info")
        self._icono.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._texto = QLabel(texto)
        self._texto.setWordWrap(True)
        self._texto.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Preferred)

        lay.addWidget(self._icono, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self._texto, 1)

        self.set_tono(tono, icono_nombre)

    def set_texto(self, texto: str) -> None:
        self._texto.setText(texto)

    def set_tono(self, tono: str, icono_nombre: str | None = None) -> None:
        if tono not in TONOS:
            tono = "info"
        nombre, token = TONOS[tono]
        self.setProperty("tono", tono)
        self._icono.set_icono(icono_nombre or nombre, color=token)
        repolish(self)

    def mostrar(self, texto: str, tono: str = "info",
                icono_nombre: str | None = None) -> None:
        self.set_texto(texto)
        self.set_tono(tono, icono_nombre)
        self.setVisible(True)


# ── Tarjeta de herramienta (menú principal) ───────────────────────────────────

class TarjetaHerramienta(QFrame):
    """Tarjeta clicable del launcher: icono grande, título y descripción.

    Es accesible por teclado (Tab + Enter/Espacio), no sólo por mouse.
    """

    activada = pyqtSignal()

    def __init__(self, *, titulo: str, descripcion: str, icono_nombre: str,
                 etiqueta_pie: str = "", tono_pie: str = "primary",
                 habilitada: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("tarjetaHerramienta")
        self.setProperty("proximamente", "false" if habilitada else "true")
        self._habilitada = habilitada
        self.setMinimumHeight(SIZE["tarjeta_h"])
        # heightForWidth: sin esto, la grilla le da a la tarjeta el alto que
        # pediría con su ancho ideal, y al angostarse la ventana la
        # descripción con word-wrap crece pero la tarjeta no: el último
        # renglón quedaba cortado por la mitad.
        politica = QSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Preferred)
        politica.setHeightForWidth(True)
        self.setSizePolicy(politica)
        if habilitada:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"])
        lay.setSpacing(SPACE["md"])

        # Insignia con el icono
        insignia = QFrame()
        insignia.setObjectName("insigniaIcono")
        insignia.setFixedSize(SIZE["icono_xl"] + 20, SIZE["icono_xl"] + 20)
        ins_lay = QVBoxLayout(insignia)
        ins_lay.setContentsMargins(0, 0, 0, 0)
        self._icono = IconoLabel(
            icono_nombre, SIZE["icono_lg"],
            color="primary" if habilitada else "text_faint")
        ins_lay.addWidget(self._icono, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(insignia)

        self._titulo = etiqueta(titulo, rol="subtitulo")
        self._titulo.setStyleSheet(f"font-size: {FS['h2']}px;")
        lay.addWidget(self._titulo)

        self._desc = etiqueta(descripcion, rol="cuerpo", wrap=True)
        lay.addWidget(self._desc, 1)

        pie = QHBoxLayout()
        pie.setContentsMargins(0, 0, 0, 0)
        pie.setSpacing(SPACE["sm"])
        if etiqueta_pie:
            pie.addWidget(Chip(etiqueta_pie, tono=tono_pie))
        pie.addStretch(1)
        self._flecha = IconoLabel(
            "flecha-der", SIZE["icono"],
            color="primary" if habilitada else "text_faint")
        pie.addWidget(self._flecha)
        lay.addLayout(pie)

        if not habilitada:
            self._titulo.setProperty("rol", "cuerpo")
            repolish(self._titulo)

    # -- geometría -----------------------------------------------------------
    def hasHeightForWidth(self) -> bool:            # noqa: N802 (API de Qt)
        return True

    def heightForWidth(self, ancho: int) -> int:    # noqa: N802 (API de Qt)
        lay = self.layout()
        if lay is None:
            return super().heightForWidth(ancho)
        return max(SIZE["tarjeta_h"], lay.heightForWidth(ancho))

    # -- interacción ---------------------------------------------------------
    def mousePressEvent(self, event):
        if self._habilitada and event.button() == Qt.MouseButton.LeftButton:
            self.activada.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if (self._habilitada
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter,
                                    Qt.Key.Key_Space)):
            self.activada.emit()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event):
        if self._habilitada:
            self.setProperty("activa", "true")
            repolish(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("activa", "false")
        repolish(self)
        super().leaveEvent(event)


# ── Barras de ventana ─────────────────────────────────────────────────────────

class BarraSuperior(QFrame):
    """Cabecera común de las ventanas de fase: título + acciones a la derecha.

    Usa alto MÍNIMO (no fijo) para tolerar escalado de fuente y DPI alto.
    """

    def __init__(self, titulo: str, parent=None, *, icono_nombre: str = ""):
        super().__init__(parent)
        self.setObjectName("cabecera")
        self.setMinimumHeight(SIZE["bar"])
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(SPACE["lg"], SPACE["sm"], SPACE["lg"], SPACE["sm"])
        self._lay.setSpacing(SPACE["md"])

        if icono_nombre:
            self._lay.addWidget(
                icono_label(icono_nombre, SIZE["icono_md"], color="primary"))

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

        self.icono_estado = IconoLabel("info", SIZE["icono"], color="text_muted")
        self.icono_estado.setVisible(False)
        self._lay.addWidget(self.icono_estado)

        self.lbl_estado = etiqueta(mensaje, rol="cuerpo")
        self.lbl_estado.setSizePolicy(QSizePolicy.Policy.Ignored,
                                      QSizePolicy.Policy.Preferred)
        self._lay.addWidget(self.lbl_estado, 1)

    def set_estado(self, texto: str, *, rol: str = "cuerpo",
                   tono: str | None = None) -> None:
        """Mensaje de estado. `tono` (ok/warn/err/info) le antepone un icono."""
        self.lbl_estado.setText(texto)
        self.lbl_estado.setProperty("rol", rol)
        self.lbl_estado.setToolTip(texto)
        repolish(self.lbl_estado)

        if tono and tono in TONOS:
            nombre, token = TONOS[tono]
            self.icono_estado.set_icono(nombre, color=token)
            self.icono_estado.setVisible(True)
        else:
            self.icono_estado.setVisible(False)

    def agregar(self, widget: QWidget) -> QWidget:
        self._lay.addWidget(widget, 0)
        return widget


# ── Buscador ──────────────────────────────────────────────────────────────────

class Buscador(QLineEdit):
    """Campo de búsqueda con la lupa dibujada dentro.

    El icono es un QLabel hijo posicionado a mano: usar addAction() habría
    dejado que Qt eligiera el color del icono, y no coincidía con el tema.
    """

    def __init__(self, marcador: str = "Buscar…", parent=None):
        super().__init__(parent)
        self.setObjectName("buscador")
        self.setPlaceholderText(marcador)
        self.setClearButtonEnabled(True)
        self._lupa = IconoLabel("buscar", 15, color="text_faint", parent=self)
        self._lupa.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._reubicar()

    def _reubicar(self) -> None:
        self._lupa.move(11, (self.height() - self._lupa.height()) // 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reubicar()


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


__all__ = [
    "Aviso",
    "AreaScroll",
    "BarraInferior",
    "BarraSuperior",
    "BotonIcono",
    "Buscador",
    "Chip",
    "FilaAdaptable",
    "IconoLabel",
    "TONOS",
    "TarjetaHerramienta",
    "abrir_en_sistema",
    "boton",
    "boton_icono",
    "elide",
    "etiqueta",
    "expansor_h",
    "icono_label",
    "selector",
    "separador",
    "separador_v",
    "sombra",
    "tarjeta",
]
