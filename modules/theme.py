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
    "bg":             "#f7f6f2",
    "surface":        "#f0ede8",
    "surface_2":      "#e8e5df",
    "surface_3":      "#dedad3",
    "surface_hover":  "#e2dfd8",
    "elevated":       "#fdfcfa",
    # Bordes
    "border":         "#cac7c0",
    "border_soft":    "#dedad3",
    # Texto
    "text":           "#1a1815",
    "text_muted":     "#63615c",
    "text_faint":     "#96948f",
    "text_inverse":   "#ffffff",
    # Primario — Teal profundo
    "primary":        "#006b71",
    "primary_h":      "#005259",
    "primary_a":      "#003d42",
    "primary_hl":     "#a8ccc9",
    "primary_soft":   "#e4f0ee",
    "on_primary":     "#ffffff",
    # Peligro
    "danger":         "#b83246",
    "danger_h":       "#8f2437",
    "danger_a":       "#6b1828",
    "danger_soft":    "#f5e0e3",
    # Éxito
    "success":        "#3d7520",
    "success_h":      "#2d5c12",
    "success_a":      "#1f4408",
    "success_soft":   "#daefd0",
    # Status bar
    "statusbar_bg":   "#ebe8e3",
    # Sombra
    "shadow":         "rgba(0,0,0,0.07)",
}

DARK = {
    # Superficies
    "bg":             "#141312",
    "surface":        "#1c1b19",
    "surface_2":      "#242320",
    "surface_3":      "#2c2b28",
    "surface_hover":  "#2e2d2a",
    "elevated":       "#211f1d",
    # Bordes
    "border":         "#3a3834",
    "border_soft":    "#302f2c",
    # Texto
    "text":           "#e8e6e1",
    "text_muted":     "#9c9a93",
    "text_faint":     "#6d6b66",
    "text_inverse":   "#141312",
    # Primario — Teal claro (contraste sobre oscuro)
    "primary":        "#4da8b0",
    "primary_h":      "#60bec7",
    "primary_a":      "#77d0d8",
    "primary_hl":     "#2b5457",
    "primary_soft":   "#162a2b",
    "on_primary":     "#0b1a1b",
    # Peligro
    "danger":         "#e8657a",
    "danger_h":       "#f07a8d",
    "danger_a":       "#f591a0",
    "danger_soft":    "#3a1c22",
    # Éxito
    "success":        "#72ba4f",
    "success_h":      "#88cc63",
    "success_a":      "#9ad978",
    "success_soft":   "#1e3318",
    # Status bar
    "statusbar_bg":   "#181715",
    # Sombra
    "shadow":         "rgba(0,0,0,0.35)",
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
}

RADIUS = {
    "sm": 5,
    "md": 7,
    "lg": 10,
    "xl": 13,
}

# Tamaños de fuente (px, coherentes con el QSS)
FS = {
    "micro": 11,
    "small": 12,
    "body":  13,
    "lead":  14,
    "h2":    16,
    "h1":    19,
}

# Alturas estándar de controles
SIZE = {
    "input":      36,
    "btn":        36,
    "btn_lg":     42,
    "btn_sm":     30,
    "bar":        58,   # alto mínimo de cabeceras / barras inferiores
    "thumb_w":    174,  # ancho base de la tarjeta de página (fase 1)
    "thumb_img":  222,  # alto del área de imagen de la tarjeta
}

# Puntos de corte para layouts responsive (px de ancho de ventana)
BREAKPOINT = {
    "sm": 620,
    "md": 820,
    "lg": 1040,
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


# ═══════════════════════════════════════════════════════════════════════════════
#  Generador de stylesheet
# ═══════════════════════════════════════════════════════════════════════════════

def _build_stylesheet(p: dict) -> str:
    r, f = RADIUS, FS
    return f"""
/* ═══ Base ═══════════════════════════════════════════════════════════════════
   IMPORTANTE: el fondo se aplica SOLO a ventanas y contenedores con nombre.
   Aplicarlo a QWidget genérico pintaba un rectángulo opaco detrás de cada
   QLabel/QFrame hijo y rompía visualmente todas las tarjetas.              */
QMainWindow, QDialog, QWidget#pantalla {{
    background-color: {p['bg']};
}}
* {{
    font-family: 'Segoe UI', 'Inter', 'Helvetica Neue', 'Noto Sans', sans-serif;
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
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p['border']};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover  {{ background: {p['text_muted']}; }}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical      {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {p['border']};
    border-radius: 5px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p['text_muted']}; }}
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
    padding: 6px 10px;
    font-size: {f['body']}px;
    color: {p['text']};
    min-height: {SIZE['input'] - 14}px;
    selection-background-color: {p['primary']};
    selection-color: {p['on_primary']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {p['primary']};
    background-color: {p['elevated']};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QTextEdit:disabled {{
    background-color: {p['surface']};
    color: {p['text_faint']};
    border-color: {p['border_soft']};
}}
QLineEdit:hover:!focus, QSpinBox:hover:!focus, QComboBox:hover:!focus {{
    border-color: {p['text_muted']};
}}
QLineEdit[invalid="true"], QLineEdit[invalid="true"]:focus {{
    border: 1px solid {p['danger']};
}}
QTextEdit[readonly="true"] {{
    background-color: {p['surface']};
    color: {p['text_muted']};
}}

/* ═══ ComboBox ══════════════════════════════════════════════════════════════ */
QComboBox::drop-down {{
    border: none;
    padding-right: 10px;
    width: 20px;
}}
QComboBox::down-arrow {{ width: 10px; height: 10px; }}
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
   Variantes vía propiedad dinámica  variant = primary | secondary | ghost
                                               | danger  | success             */
QPushButton {{
    background-color: {p['primary']};
    color: {p['on_primary']};
    border: 1px solid transparent;
    border-radius: {r['md']}px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: {f['body']}px;
    min-height: {SIZE['btn'] - 18}px;
}}
QPushButton:hover   {{ background-color: {p['primary_h']}; }}
QPushButton:pressed {{ background-color: {p['primary_a']}; }}
QPushButton:focus   {{ border: 1px solid {p['text']}; }}
QPushButton:disabled {{
    background-color: {p['surface_3']};
    color: {p['text_faint']};
    border-color: transparent;
}}

QPushButton[variant="danger"] {{
    background-color: {p['danger']};
    color: #ffffff;
}}
QPushButton[variant="danger"]:hover   {{ background-color: {p['danger_h']}; }}
QPushButton[variant="danger"]:pressed {{ background-color: {p['danger_a']}; }}

QPushButton[variant="success"] {{
    background-color: {p['success']};
    color: #ffffff;
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
    border-color: {p['text_muted']};
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
    color: #ffffff;
}}
QPushButton[variant="ghost"]:checked {{
    background-color: {p['primary_soft']};
    color: {p['primary']};
    border-color: {p['primary']};
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
    background-color: {p['primary_soft']};
    border: 1px solid {p['primary_hl']};
    border-radius: {r['xl']}px;
}}
QFrame#panelVacio {{
    background-color: {p['surface']};
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
    border-color: {p['primary']};
    background-color: {p['surface_2']};
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
    background-color: {p['surface_hover']};
    border-color: {p['border_soft']};
}}
QListWidget::item:selected {{
    background-color: {p['primary_soft']};
    border-color: {p['primary']};
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
    border-radius: 5px;
    max-height: 8px;
}}
QProgressBar::chunk {{
    background: {p['primary']};
    border-radius: 5px;
}}

/* ═══ Labels con rol ═════════════════════════════════════════════════════════
   Se usan como  lbl.setProperty("rol", "...")  o por objectName.             */
QLabel#seccion, QLabel[rol="seccion"] {{
    font-size: {f['micro']}px;
    font-weight: 700;
    color: {p['text_faint']};
    letter-spacing: 1.4px;
}}
QLabel#appTitle, QLabel[rol="titulo"] {{
    font-size: {f['h1']}px;
    font-weight: 700;
    color: {p['text']};
    letter-spacing: -0.3px;
}}
QLabel[rol="tituloBarra"] {{
    font-size: {f['lead']}px;
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
    color: {p['primary']};
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

    app.setPalette(_build_palette(palette))
    app.setStyleSheet(_build_stylesheet(palette))
    app.setFont(QFont("Segoe UI", font_pt(10)))

    theme_signals.changed.emit(mode)
