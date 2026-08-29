"""
modules/theme.py
============================================================
Sistema de diseño unificado para PDF Sign Assistant.

Esta es la ÚNICA fuente de verdad visual de la app: ningún otro
módulo debe declarar colores, tamaños ni radios a mano.

Provee:
  - Paletas LIGHT y DARK
  - Tokens de espaciado (SPACE), radios (RADIUS) y tipografía (FS)
  - STYLESHEET completo que se aplica a toda la app
  - QPalette sincronizada (para diálogos nativos: QFileDialog,
    QMessageBox, QPrintDialog… que no se pintan solo con QSS)
  - apply_theme(app, mode) para cambiar el tema en runtime
  - theme_signals.changed → señal para que las ventanas abiertas
    se repinten sin reiniciar la app
  - font_pt(pt) para tamaños de fuente seguros (siempre >= 1)

Uso:
    from modules.theme import apply_theme, THEME, font_pt
    apply_theme(app, "dark")   # o "light"

Notas de mantenimiento (aprendidas a los golpes)
------------------------------------------------
1. El color de fondo se aplica SOLO a ventanas y contenedores con
   objectName propio. Puesto sobre `QWidget` genérico, Qt pinta un
   rectángulo opaco detrás de cada hijo y rompe todas las tarjetas.
2. Al `QCheckBox::indicator` no se le pinta fondo: en cuanto se hace,
   Qt deja de dibujar el tilde y queda un cuadrado lleno ambiguo.
3. QSS no soporta box-shadow. Para dar profundidad se usa
   `modules.ui.sombra()`, que aplica un QGraphicsDropShadowEffect.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

# ═══════════════════════════════════════════════════════════════════════════════
#  Paletas
# ═══════════════════════════════════════════════════════════════════════════════

LIGHT = {
    # Superficies
    "bg":             "#f5f6f8",
    "surface":        "#ffffff",
    "surface_2":      "#eef1f4",
    "surface_3":      "#e2e6ec",
    "surface_hover":  "#e8ecf1",
    "elevated":       "#ffffff",
    "sidebar":        "#ffffff",
    # Bordes
    "border":         "#d3d9e0",
    "border_soft":    "#e4e8ee",
    "border_fuerte":  "#b9c2cd",
    # Texto
    "text":           "#101720",
    "text_muted":     "#57626f",
    "text_faint":     "#8a94a1",
    "text_inverse":   "#ffffff",
    # Primario — Teal profundo
    "primary":        "#0d7068",
    "primary_h":      "#0a5c55",
    "primary_a":      "#084842",
    "primary_hl":     "#8fcdc6",
    "primary_soft":   "#e3f2f0",
    "on_primary":     "#ffffff",
    # Peligro
    "danger":         "#b8253f",
    "danger_h":       "#951c33",
    "danger_a":       "#711526",
    "danger_soft":    "#fbe6ea",
    "on_danger":      "#ffffff",
    # Éxito
    "success":        "#1c7a3e",
    "success_h":      "#156130",
    "success_a":      "#0f4a24",
    "success_soft":   "#e0f4e6",
    "on_success":     "#ffffff",
    # Advertencia
    "warning":        "#a35a08",
    "warning_h":      "#834806",
    "warning_soft":   "#fdefdc",
    # Informativo
    "info":           "#1f52c4",
    "info_soft":      "#e6ecfb",
    # Barra de estado
    "statusbar_bg":   "#eef1f4",
    # Sombra (la usa ui.sombra(), no el QSS)
    "shadow":         "rgba(16,23,32,0.13)",
}

DARK = {
    # Superficies
    "bg":             "#0e1218",
    "surface":        "#171c23",
    "surface_2":      "#1e242c",
    "surface_3":      "#272e38",
    "surface_hover":  "#232a33",
    "elevated":       "#1b212a",
    "sidebar":        "#12171d",
    # Bordes
    "border":         "#2e3742",
    "border_soft":    "#232a33",
    "border_fuerte":  "#414c59",
    # Texto
    "text":           "#e7ecf2",
    "text_muted":     "#98a3b1",
    "text_faint":     "#6a7583",
    "text_inverse":   "#0e1218",
    # Primario — Teal claro (contraste sobre oscuro)
    "primary":        "#33c7b7",
    "primary_h":      "#57d6c8",
    "primary_a":      "#7ce3d8",
    "primary_hl":     "#1c6b63",
    "primary_soft":   "#10302e",
    "on_primary":     "#04211e",
    # Peligro
    "danger":         "#f4718a",
    "danger_h":       "#f88b9f",
    "danger_a":       "#fba5b5",
    "danger_soft":    "#3a1a22",
    # Sobre un relleno claro en modo oscuro el texto va oscuro: blanco
    # sobre rosa/verde pastel no llega al contraste mínimo legible.
    "on_danger":      "#3c0c17",
    # Éxito
    "success":        "#57cc7a",
    "success_h":      "#75da93",
    "success_a":      "#92e5aa",
    "success_soft":   "#12301d",
    "on_success":     "#07260f",
    # Advertencia
    "warning":        "#e8a33c",
    "warning_h":      "#f0b55c",
    "warning_soft":   "#332310",
    # Informativo
    "info":           "#6d9cf5",
    "info_soft":      "#141f36",
    # Barra de estado
    "statusbar_bg":   "#12171d",
    # Sombra
    "shadow":         "rgba(0,0,0,0.5)",
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Tokens de layout — usar SIEMPRE estos valores, no números sueltos
# ═══════════════════════════════════════════════════════════════════════════════

SPACE = {
    "xs":  4,
    "sm":  8,
    "md":  12,
    "lg":  16,
    "xl":  24,
    "2xl": 32,
    "3xl": 44,
}

RADIUS = {
    "sm": 6,
    "md": 8,
    "lg": 12,
    "xl": 16,
    "full": 999,
}

# Tamaños de fuente (px, coherentes con el QSS)
FS = {
    "micro":   11,
    "small":   12,
    "body":    13,
    "lead":    14,
    "h3":      15,
    "h2":      17,
    "h1":      20,
    "display": 26,
}

# Alturas estándar de controles y medidas de layout
SIZE = {
    "input":      36,
    "btn":        36,
    "btn_lg":     42,
    "btn_sm":     30,
    "bar":        60,   # alto mínimo de cabeceras / barras inferiores
    "thumb_w":    174,  # ancho base de la tarjeta de página (fase 1)
    "thumb_img":  222,  # alto del área de imagen de la tarjeta
    "sidebar":    236,  # ancho de la barra lateral expandida
    "rail":       64,   # ancho cuando se colapsa a sólo iconos
    "nav":        40,   # alto de un ítem de navegación
    "icono":      18,   # icono dentro de un botón o etiqueta
    "icono_md":   22,
    "icono_lg":   28,   # icono de encabezado
    "icono_xl":   40,   # icono de tarjeta de herramienta
    "tarjeta_h":  190,  # alto de la tarjeta del launcher
    "miniatura":  138,  # alto de la miniatura en la lista de escaneo
}

# Puntos de corte para layouts responsive (px de ancho de ventana)
BREAKPOINT = {
    "sm": 620,
    "md": 820,
    "lg": 1040,
    "xl": 1320,
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Estado global del tema
# ═══════════════════════════════════════════════════════════════════════════════

THEME: dict = dict(LIGHT)   # paleta activa (mutable)
_current_mode: str = "light"


class _ThemeSignals(QObject):
    """Emite el nuevo modo cuando cambia el tema, para que las ventanas
    ya abiertas puedan re-aplicar estilos locales sin reiniciarse."""
    changed = pyqtSignal(str)


theme_signals = _ThemeSignals()


def current_mode() -> str:
    return _current_mode


def is_dark() -> bool:
    return _current_mode == "dark"


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def font_pt(pt: int | float) -> int:
    """Devuelve el tamaño de fuente, garantizando que sea >= 1."""
    return max(1, int(pt))


def repolish(widget: QWidget) -> None:
    """Recalcula el estilo de un widget tras cambiar una propiedad dinámica."""
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def set_prop(widget: QWidget, nombre: str, valor) -> None:
    """Setea una propiedad dinámica y repinta el widget."""
    widget.setProperty(nombre, valor)
    repolish(widget)


def color(token: str, alterno: str = "") -> str:
    """Color del tema activo por nombre de token.

    Acepta también un color literal ('#ff0000'), que devuelve tal cual:
    así las funciones que reciben `color=` de afuera no tienen que
    distinguir entre token y valor.
    """
    return THEME.get(token, alterno or token)


# ═══════════════════════════════════════════════════════════════════════════════
#  Generador de stylesheet
# ═══════════════════════════════════════════════════════════════════════════════

def _archivo_flecha(p: dict, modo: str) -> str:
    """Escribe el chevron del desplegable y devuelve su ruta para el QSS.

    Hace falta un ARCHIVO porque `image: url(...)` no acepta otra cosa, y
    los iconos de esta app se dibujan en memoria desde SVG. Se guarda uno
    por tema, con el color del texto atenuado, y se reescribe en cada
    cambio de tema: son 300 bytes.

    Si algo falla se devuelve "", y la regla del QSS se omite: quedaría el
    desplegable sin flecha, que es feo pero no rompe nada.
    """
    try:
        import tempfile
        from pathlib import Path

        from modules.iconos import pixmap

        destino = Path(tempfile.gettempdir()) / f"pdfsign_chevron_{modo}.png"
        pm = pixmap("chevron-abajo", 10, color=p["text_muted"])
        if pm.isNull() or not pm.save(str(destino), "PNG"):
            return ""
        # QSS quiere barras normales incluso en Windows.
        return str(destino).replace("\\", "/")
    except Exception:                                    # noqa: BLE001
        return ""


def _build_stylesheet(p: dict, flecha: str = "") -> str:
    r, f, s = RADIUS, FS, SIZE
    # La flecha necesita SÍ o SÍ una imagen: en cuanto una hoja de estilo
    # toca ::drop-down, Qt deja de dibujar el control nativo. Con una regla
    # de tamaño y sin imagen —como estaba— el desplegable quedaba sin
    # ninguna marca, indistinguible de un campo de texto. Sin archivo, se
    # omite la regla y al menos vuelve el dibujo por defecto de Qt.
    # Llaves simples: esto se inserta como VALOR en la plantilla de abajo,
    # no se vuelve a interpretar como f-string.
    regla_flecha = (
        f"QComboBox::down-arrow {{ image: url({flecha}); "
        f"width: 10px; height: 10px; }}" if flecha else "")
    return f"""
/* ═══ Base ═══════════════════════════════════════════════════════════════════
   El fondo se aplica SOLO a ventanas y contenedores con nombre. Aplicarlo a
   QWidget genérico pintaba un rectángulo opaco detrás de cada hijo.        */
QMainWindow, QDialog, QWidget#pantalla {{
    background-color: {p['bg']};
}}
* {{
    font-family: 'Segoe UI Variable Text', 'Segoe UI', 'Inter',
                 'SF Pro Text', 'Noto Sans', sans-serif;
    color: {p['text']};
}}
QWidget {{
    font-size: {f['body']}px;
}}
QLabel {{
    background: transparent;
    color: {p['text']};
}}
QFrame {{
    background: transparent;
}}

/* ═══ Scroll bars ════════════════════════════════════════════════════════════ */
QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p['border']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover  {{ background: {p['text_faint']}; }}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical      {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {p['border']};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p['text_faint']}; }}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal     {{ width: 0; }}

QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ═══ Inputs ═════════════════════════════════════════════════════════════════ */
QLineEdit, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: {p['elevated']};
    border: 1px solid {p['border']};
    border-radius: {r['md']}px;
    padding: 6px 11px;
    font-size: {f['body']}px;
    color: {p['text']};
    min-height: {s['input'] - 14}px;
    selection-background-color: {p['primary']};
    selection-color: {p['on_primary']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {p['primary']};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QTextEdit:disabled {{
    background-color: {p['surface_2']};
    color: {p['text_faint']};
    border-color: {p['border_soft']};
}}
QLineEdit:hover:!focus, QSpinBox:hover:!focus, QComboBox:hover:!focus {{
    border-color: {p['border_fuerte']};
}}
QLineEdit[invalid="true"], QLineEdit[invalid="true"]:focus {{
    border: 1px solid {p['danger']};
}}
QTextEdit[readonly="true"] {{
    background-color: {p['surface_2']};
    color: {p['text_muted']};
}}
/* Buscador: deja lugar al icono de lupa que se dibuja adentro */
QLineEdit#buscador {{
    padding-left: 32px;
    background-color: {p['surface_2']};
    border-color: transparent;
}}
QLineEdit#buscador:focus {{
    background-color: {p['elevated']};
    border-color: {p['primary']};
}}

/* ═══ ComboBox ══════════════════════════════════════════════════════════════ */
QComboBox::drop-down {{
    border: none;
    padding-right: 10px;
    width: 20px;
}}
/* La flecha necesita SÍ o SÍ una imagen: en cuanto una hoja de estilo
   toca ::drop-down, Qt deja de dibujar el control nativo. Con la regla
   de tamaño y sin imagen —como estaba— el desplegable quedaba sin
   ninguna marca, indistinguible de un campo de texto. */
{regla_flecha}
QComboBox QAbstractItemView {{
    background-color: {p['elevated']};
    border: 1px solid {p['border']};
    border-radius: {r['md']}px;
    selection-background-color: {p['primary']};
    selection-color: {p['on_primary']};
    color: {p['text']};
    padding: 4px;
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: 6px 10px;
    border-radius: {r['sm']}px;
    min-height: 22px;
}}

/* ═══ SpinBox ════════════════════════════════════════════════════════════════ */
QSpinBox::up-button, QSpinBox::down-button {{
    background: {p['surface_2']};
    border: none;
    width: 18px;
    border-radius: 3px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: {p['surface_hover']};
}}

/* ═══ Botones ════════════════════════════════════════════════════════════════
   Variantes vía propiedad dinámica
     variant = primary | secondary | ghost | danger | success | nav | plano   */
QPushButton {{
    background-color: {p['primary']};
    color: {p['on_primary']};
    border: 1px solid transparent;
    border-radius: {r['md']}px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: {f['body']}px;
    min-height: {s['btn'] - 18}px;
}}
QPushButton:hover   {{ background-color: {p['primary_h']}; }}
QPushButton:pressed {{ background-color: {p['primary_a']}; }}
QPushButton:focus   {{ border: 1px solid {p['text']}; }}
QPushButton:disabled {{
    background-color: {p['surface_3']};
    color: {p['text_faint']};
    border-color: transparent;
}}

/* Compacto: botones angostos de acción rápida (rotar, ±90°…), donde el
   padding normal de 18px se comería el texto. */
QPushButton[compacto="true"] {{
    padding: 4px 9px;
    font-size: {f['small']}px;
}}
/* Sólo icono: cuadrado, sin padding lateral que descentre el dibujo. */
QPushButton[soloicono="true"] {{
    padding: 0;
}}

QPushButton[variant="danger"] {{
    background-color: {p['danger']};
    color: {p['on_danger']};
}}
QPushButton[variant="danger"]:hover   {{ background-color: {p['danger_h']}; }}
QPushButton[variant="danger"]:pressed {{ background-color: {p['danger_a']}; }}

QPushButton[variant="success"] {{
    background-color: {p['success']};
    color: {p['on_success']};
}}
QPushButton[variant="success"]:hover   {{ background-color: {p['success_h']}; }}
QPushButton[variant="success"]:pressed {{ background-color: {p['success_a']}; }}

QPushButton[variant="secondary"] {{
    background-color: transparent;
    color: {p['primary']};
    border: 1px solid {p['primary']};
}}
QPushButton[variant="secondary"]:hover {{
    background-color: {p['primary']};
    color: {p['on_primary']};
}}
QPushButton[variant="secondary"]:pressed {{
    background-color: {p['primary_h']};
    color: {p['on_primary']};
}}
QPushButton[variant="secondary"]:disabled {{
    background-color: transparent;
    color: {p['text_faint']};
    border-color: {p['border_soft']};
}}

QPushButton[variant="ghost"] {{
    background-color: transparent;
    color: {p['text_muted']};
    border: 1px solid {p['border']};
    font-weight: 500;
}}
QPushButton[variant="ghost"]:hover {{
    background-color: {p['surface_2']};
    color: {p['text']};
    border-color: {p['border_fuerte']};
}}
QPushButton[variant="ghost"]:pressed {{ background-color: {p['surface_3']}; }}
QPushButton[variant="ghost"]:disabled {{
    background-color: transparent;
    color: {p['text_faint']};
    border-color: {p['border_soft']};
}}
QPushButton[variant="ghost"][danger="true"] {{
    color: {p['danger']};
    border-color: {p['danger']};
}}
QPushButton[variant="ghost"][danger="true"]:hover {{
    background-color: {p['danger']};
    color: {p['on_danger']};
}}
QPushButton[variant="ghost"]:checked {{
    background-color: {p['primary_soft']};
    color: {p['primary']};
    border-color: {p['primary']};
}}

/* Plano: sin borde, para acciones terciarias dentro de una tarjeta. */
QPushButton[variant="plano"] {{
    background-color: transparent;
    color: {p['text_muted']};
    border: 1px solid transparent;
    font-weight: 500;
    padding: 6px 10px;
    /* Alineado a la izquierda: cuando el botón ocupa todo el ancho (una
       fila de "documentos recientes"), centrado se lee como un título
       suelto en vez de como un ítem de lista. */
    text-align: left;
}}
QPushButton[variant="plano"]:hover {{
    background-color: {p['surface_2']};
    color: {p['text']};
}}
QPushButton[variant="plano"]:pressed {{ background-color: {p['surface_3']}; }}
QPushButton[variant="plano"]:disabled {{ color: {p['text_faint']}; }}

/* Navegación de la barra lateral: texto a la izquierda, sin borde,
   estado activo marcado con fondo suave. */
QPushButton[variant="nav"] {{
    background-color: transparent;
    color: {p['text_muted']};
    border: 1px solid transparent;
    border-radius: {r['md']}px;
    padding: 0 12px;
    font-weight: 500;
    font-size: {f['body']}px;
    text-align: left;
    min-height: {s['nav']}px;
}}
QPushButton[variant="nav"]:hover {{
    background-color: {p['surface_2']};
    color: {p['text']};
}}
QPushButton[variant="nav"]:checked {{
    background-color: {p['primary_soft']};
    color: {p['primary']};
    font-weight: 600;
}}
QPushButton[variant="nav"]:disabled {{ color: {p['text_faint']}; }}

/* ═══ Checkbox ═══════════════════════════════════════════════════════════════
   El indicador se deja al estilo nativo: al pintarle un fondo propio, Qt
   deja de dibujar el tilde y queda un cuadrado lleno, ambiguo. El color de
   marcado sale de la QPalette (Highlight = primary).                        */
QCheckBox {{
    spacing: 8px;
    color: {p['text']};
    font-size: {f['body']}px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
}}

/* ═══ Tarjetas y contenedores ════════════════════════════════════════════════ */
QFrame#card {{
    background-color: {p['surface']};
    border: 1px solid {p['border_soft']};
    border-radius: {r['lg']}px;
}}
QFrame#cardAcento {{
    background-color: {p['primary_soft']};
    border: 1px solid {p['primary_hl']};
    border-radius: {r['lg']}px;
}}
QFrame#panelActivo {{
    background-color: {p['surface']};
    border: 1px solid {p['border_soft']};
    border-left: 3px solid {p['primary']};
    border-radius: {r['lg']}px;
}}
QFrame#panelVacio {{
    background-color: transparent;
    border: 1px dashed {p['border']};
    border-radius: {r['xl']}px;
}}
QFrame#cabecera {{
    background-color: {p['surface']};
    border: none;
    border-bottom: 1px solid {p['border_soft']};
}}
QFrame#barraInferior {{
    background-color: {p['surface']};
    border: none;
    border-top: 1px solid {p['border_soft']};
}}
QFrame#separadorV {{
    background-color: {p['border_soft']};
    max-width: 1px;
    border: none;
}}

/* ═══ Barra lateral (menú de herramientas) ═══════════════════════════════════ */
QWidget#barraLateral {{
    background-color: {p['sidebar']};
    border-right: 1px solid {p['border_soft']};
}}
QFrame#marca {{
    background: transparent;
    border: none;
}}
QLabel#marcaTitulo {{
    font-size: {f['h3']}px;
    font-weight: 700;
    color: {p['text']};
    letter-spacing: -0.2px;
}}
QLabel#marcaVersion {{
    font-size: {f['micro']}px;
    color: {p['text_faint']};
}}

/* ═══ Tarjeta de herramienta (launcher) ══════════════════════════════════════ */
QFrame#tarjetaHerramienta {{
    background-color: {p['surface']};
    border: 1px solid {p['border_soft']};
    border-radius: {r['xl']}px;
}}
QFrame#tarjetaHerramienta:hover {{
    border-color: {p['primary']};
    background-color: {p['surface']};
}}
QFrame#tarjetaHerramienta[activa="true"] {{
    border-color: {p['primary']};
}}
QFrame#tarjetaHerramienta[proximamente="true"] {{
    background-color: transparent;
    border: 1px dashed {p['border']};
}}
QFrame#insigniaIcono {{
    background-color: {p['primary_soft']};
    border: none;
    border-radius: {r['lg']}px;
}}

/* ═══ Zona de drag & drop ════════════════════════════════════════════════════ */
QFrame#zonaDrop {{
    background-color: {p['surface_2']};
    border: 2px dashed {p['border']};
    border-radius: {r['lg']}px;
}}
QFrame#zonaDrop[activo="true"] {{
    background-color: {p['primary_soft']};
    border: 2px dashed {p['primary']};
}}

/* ═══ Tarjeta de página (fase 1) ═════════════════════════════════════════════ */
QFrame#tarjetaPagina {{
    background-color: {p['surface']};
    border: 2px solid {p['border_soft']};
    border-radius: {r['lg']}px;
}}
QFrame#tarjetaPagina:hover {{
    border-color: {p['primary_hl']};
}}
QFrame#tarjetaPagina[activa="true"] {{
    background-color: {p['primary_soft']};
    border-color: {p['primary']};
}}
QFrame#tarjetaPagina:focus {{
    border-color: {p['primary']};
}}
QLabel#lienzoPagina {{
    background-color: {p['surface_3']};
    border-radius: {r['sm']}px;
}}

/* ═══ Fila de página escaneada ═══════════════════════════════════════════════ */
QFrame#filaPagina {{
    background-color: {p['surface']};
    border: 1px solid {p['border_soft']};
    border-radius: {r['lg']}px;
}}
QFrame#filaPagina:hover {{
    border-color: {p['border_fuerte']};
}}
QFrame#filaPagina[activa="true"] {{
    border-color: {p['primary']};
    background-color: {p['primary_soft']};
}}
QLabel#miniatura {{
    background-color: {p['surface_3']};
    border: 1px solid {p['border_soft']};
    border-radius: {r['sm']}px;
}}
QLabel#numeroPagina {{
    background-color: {p['surface_3']};
    color: {p['text_muted']};
    border-radius: {r['sm']}px;
    font-size: {f['micro']}px;
    font-weight: 700;
    padding: 3px 7px;
}}

/* ═══ Lista de guardados ═════════════════════════════════════════════════════ */
QListWidget {{
    background-color: {p['surface']};
    border: 1px solid {p['border_soft']};
    border-radius: {r['lg']}px;
    padding: 6px;
    outline: none;
}}
QListWidget::item {{
    border-radius: {r['md']}px;
    padding: 9px 12px;
    margin: 2px 0;
    color: {p['text']};
    border: 1px solid transparent;
}}
QListWidget::item:hover {{
    background-color: {p['surface_2']};
}}
QListWidget::item:selected {{
    background-color: {p['primary_soft']};
    border-color: {p['primary_hl']};
    color: {p['text']};
}}

/* ═══ Separadores ════════════════════════════════════════════════════════════ */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {p['border_soft']};
    max-height: 1px;
    border: none;
    background-color: {p['border_soft']};
}}

/* ═══ Barra de progreso ══════════════════════════════════════════════════════ */
QProgressBar {{
    background: {p['surface_3']};
    border: none;
    border-radius: 4px;
    max-height: 7px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {p['primary']};
    border-radius: 4px;
}}

/* ═══ Labels con rol ═════════════════════════════════════════════════════════
   Se usan como  lbl.setProperty("rol", "...")  o por objectName.             */
QLabel#seccion, QLabel[rol="seccion"] {{
    font-size: {f['micro']}px;
    font-weight: 700;
    color: {p['text_faint']};
    letter-spacing: 1.2px;
}}
QLabel[rol="display"] {{
    font-size: {f['display']}px;
    font-weight: 700;
    color: {p['text']};
    letter-spacing: -0.6px;
}}
QLabel#appTitle, QLabel[rol="titulo"] {{
    font-size: {f['h1']}px;
    font-weight: 700;
    color: {p['text']};
    letter-spacing: -0.3px;
}}
QLabel[rol="tituloBarra"] {{
    font-size: {f['h3']}px;
    font-weight: 600;
    color: {p['text']};
}}
QLabel#nombreActivo, QLabel[rol="subtitulo"] {{
    font-size: {f['lead']}px;
    font-weight: 600;
    color: {p['text']};
}}
QLabel#fechaItem, QLabel[rol="hint"] {{
    font-size: {f['micro']}px;
    color: {p['text_muted']};
}}
QLabel[rol="cuerpo"] {{
    font-size: {f['body']}px;
    color: {p['text_muted']};
}}
QLabel[rol="ok"] {{
    font-size: {f['body']}px;
    font-weight: 600;
    color: {p['success']};
}}
QLabel[rol="error"] {{
    font-size: {f['small']}px;
    font-weight: 600;
    color: {p['danger']};
}}
QLabel[rol="badge"] {{
    font-size: {f['micro']}px;
    color: {p['primary']};
    background-color: {p['primary_soft']};
    border: 1px solid {p['primary_hl']};
    border-radius: {r['sm']}px;
    padding: 6px 10px;
}}

/* ═══ Chips de estado ════════════════════════════════════════════════════════
   Píldora chica con icono + texto. tono = neutro|ok|warn|err|info|primary   */
QFrame#chip {{
    border-radius: {r['sm']}px;
    border: 1px solid {p['border_soft']};
    background-color: {p['surface_2']};
}}
QFrame#chip QLabel {{
    font-size: {f['micro']}px;
    font-weight: 600;
    color: {p['text_muted']};
}}
QFrame#chip[tono="ok"] {{
    background-color: {p['success_soft']};
    border-color: transparent;
}}
QFrame#chip[tono="ok"] QLabel      {{ color: {p['success']}; }}
QFrame#chip[tono="warn"] {{
    background-color: {p['warning_soft']};
    border-color: transparent;
}}
QFrame#chip[tono="warn"] QLabel    {{ color: {p['warning']}; }}
QFrame#chip[tono="err"] {{
    background-color: {p['danger_soft']};
    border-color: transparent;
}}
QFrame#chip[tono="err"] QLabel     {{ color: {p['danger']}; }}
QFrame#chip[tono="info"] {{
    background-color: {p['info_soft']};
    border-color: transparent;
}}
QFrame#chip[tono="info"] QLabel    {{ color: {p['info']}; }}
QFrame#chip[tono="primary"] {{
    background-color: {p['primary_soft']};
    border-color: transparent;
}}
QFrame#chip[tono="primary"] QLabel {{ color: {p['primary']}; }}

/* ═══ Avisos en línea ════════════════════════════════════════════════════════ */
QFrame#aviso {{
    border-radius: {r['md']}px;
    border: 1px solid {p['border_soft']};
    background-color: {p['surface_2']};
}}
QFrame#aviso[tono="ok"]      {{ background-color: {p['success_soft']};
                                border-color: transparent; }}
QFrame#aviso[tono="warn"]    {{ background-color: {p['warning_soft']};
                                border-color: transparent; }}
QFrame#aviso[tono="err"]     {{ background-color: {p['danger_soft']};
                                border-color: transparent; }}
QFrame#aviso[tono="info"]    {{ background-color: {p['info_soft']};
                                border-color: transparent; }}
QFrame#aviso[tono="primary"] {{ background-color: {p['primary_soft']};
                                border-color: transparent; }}

/* ═══ Status bar ════════════════════════════════════════════════════════════ */
QStatusBar {{
    background-color: {p['statusbar_bg']};
    border-top: 1px solid {p['border_soft']};
    font-size: {f['small']}px;
    color: {p['text_muted']};
    padding: 3px 10px;
}}
QStatusBar::item {{ border: none; }}

/* ═══ Message Box / diálogos nativos ════════════════════════════════════════ */
QMessageBox {{ background-color: {p['bg']}; }}
QMessageBox QLabel {{ color: {p['text']}; font-size: {f['body']}px; }}
QMessageBox QPushButton {{ min-width: 84px; min-height: 30px; }}

/* ═══ ToolTip ════════════════════════════════════════════════════════════════ */
QToolTip {{
    background-color: {p['surface_3']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: {r['sm']}px;
    padding: 5px 8px;
    font-size: {f['small']}px;
}}
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  QPalette — necesaria para diálogos nativos que ignoran el QSS
# ═══════════════════════════════════════════════════════════════════════════════

def _build_palette(p: dict) -> QPalette:
    pal = QPalette()
    C = QPalette.ColorRole
    G = QPalette.ColorGroup

    pal.setColor(C.Window,          QColor(p["bg"]))
    pal.setColor(C.WindowText,      QColor(p["text"]))
    pal.setColor(C.Base,            QColor(p["elevated"]))
    pal.setColor(C.AlternateBase,   QColor(p["surface_2"]))
    pal.setColor(C.Text,            QColor(p["text"]))
    pal.setColor(C.Button,          QColor(p["surface"]))
    pal.setColor(C.ButtonText,      QColor(p["text"]))
    pal.setColor(C.BrightText,      QColor(p["danger"]))
    pal.setColor(C.Highlight,       QColor(p["primary"]))
    pal.setColor(C.HighlightedText, QColor(p["on_primary"]))
    pal.setColor(C.ToolTipBase,     QColor(p["surface_3"]))
    pal.setColor(C.ToolTipText,     QColor(p["text"]))
    pal.setColor(C.PlaceholderText, QColor(p["text_faint"]))
    pal.setColor(C.Link,            QColor(p["primary"]))

    for grupo in (G.Disabled,):
        pal.setColor(grupo, C.WindowText, QColor(p["text_faint"]))
        pal.setColor(grupo, C.Text,       QColor(p["text_faint"]))
        pal.setColor(grupo, C.ButtonText, QColor(p["text_faint"]))
    return pal


# ═══════════════════════════════════════════════════════════════════════════════
#  Aplicar tema
# ═══════════════════════════════════════════════════════════════════════════════

def apply_theme(app: QApplication, mode: str = "light") -> None:
    """
    Aplica el tema 'light' o 'dark' a toda la aplicación.

    Actualiza THEME (paleta activa), el stylesheet, la QPalette y emite
    theme_signals.changed para que las ventanas abiertas se actualicen.
    """
    global _current_mode
    mode = "dark" if str(mode).lower() == "dark" else "light"
    _current_mode = mode
    palette = LIGHT if mode == "light" else DARK

    THEME.clear()
    THEME.update(palette)

    # Los iconos llevan el color quemado en el pixmap: si no se tira el
    # cache, tras cambiar de tema quedarían del color anterior.
    try:
        from modules.iconos import limpiar_cache

        limpiar_cache()
    except ImportError:                                # pragma: no cover
        pass

    app.setPalette(_build_palette(palette))
    app.setStyleSheet(_build_stylesheet(
        palette, _archivo_flecha(palette, mode)))
    app.setFont(QFont("Segoe UI", font_pt(10)))

    theme_signals.changed.emit(mode)
