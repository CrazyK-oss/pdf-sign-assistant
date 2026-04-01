"""
modules/theme.py
============================================================
Sistema de diseño unificado para PDF Sign Assistant.

Provee:
  - Paletas LIGHT y DARK
  - STYLESHEET completo que se aplica a toda la app
  - Función apply_theme(app, mode) para cambiar el tema en runtime
  - Función font_pt(pt) para definir tamaños de fuente de forma
    segura (siempre >= 1, evita el warning de Qt sobre tamaños <= 0)

Uso:
    from modules.theme import apply_theme, THEME, font_pt
    apply_theme(app, "dark")   # o "light"
"""

from __future__ import annotations
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QPalette, QColor


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
    # Bordes
    "border":         "#cac7c0",
    "border_soft":    "#dedad3",
    # Texto
    "text":           "#1a1815",
    "text_muted":     "#6b6963",
    "text_faint":     "#aba9a4",
    "text_inverse":   "#ffffff",
    # Primario — Teal profundo
    "primary":        "#006b71",
    "primary_h":      "#005259",
    "primary_a":      "#003d42",
    "primary_hl":     "#c5dbd9",
    "primary_soft":   "#e4f0ee",
    # Peligro
    "danger":         "#b83246",
    "danger_h":       "#8f2437",
    "danger_a":       "#6b1828",
    "danger_soft":    "#f5e0e3",
    # Éxito
    "success":        "#3d7520",
    "success_h":      "#2d5c12",
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
    # Bordes
    "border":         "#3a3834",
    "border_soft":    "#302f2c",
    # Texto
    "text":           "#e8e6e1",
    "text_muted":     "#8a8880",
    "text_faint":     "#55534f",
    "text_inverse":   "#141312",
    # Primario — Teal claro (contraste sobre oscuro)
    "primary":        "#4da8b0",
    "primary_h":      "#60bec7",
    "primary_a":      "#77d0d8",
    "primary_hl":     "#1e3b3d",
    "primary_soft":   "#162a2b",
    # Peligro
    "danger":         "#e8657a",
    "danger_h":       "#f07a8d",
    "danger_a":       "#f591a0",
    "danger_soft":    "#3a1c22",
    # Éxito
    "success":        "#72ba4f",
    "success_h":      "#88cc63",
    "success_soft":   "#1e3318",
    # Status bar
    "statusbar_bg":   "#181715",
    # Sombra
    "shadow":         "rgba(0,0,0,0.35)",
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Estado global del tema
# ═══════════════════════════════════════════════════════════════════════════════

THEME: dict = dict(LIGHT)   # paleta activa (mutable)
_current_mode: str = "light"


def current_mode() -> str:
    return _current_mode


# ═══════════════════════════════════════════════════════════════════════════════
#  Helper de fuentes (evita el warning "Point size <= 0")
# ═══════════════════════════════════════════════════════════════════════════════

def font_pt(pt: int | float) -> int:
    """Devuelve el tamaño de fuente, garantizando que sea >= 1."""
    return max(1, int(pt))


# ═══════════════════════════════════════════════════════════════════════════════
#  Generador de stylesheet
# ═══════════════════════════════════════════════════════════════════════════════

def _build_stylesheet(p: dict) -> str:
    return f"""
/* ═══ Base ═══════════════════════════════════════════════════════════════════ */
QMainWindow, QDialog, QWidget {{
    background-color: {p['bg']};
    color: {p['text']};
    font-family: 'Segoe UI', 'Inter', 'Helvetica Neue', sans-serif;
    font-size: 13px;
}}

/* ═══ Scroll bars ════════════════════════════════════════════════════════════ */
QScrollBar:vertical {{
    background: {p['surface']};
    width: 8px;
    border-radius: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p['border']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover  {{ background: {p['text_muted']}; }}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical      {{ height: 0; }}
QScrollBar:horizontal {{
    background: {p['surface']};
    height: 8px;
    border-radius: 4px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {p['border']};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p['text_muted']}; }}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal     {{ width: 0; }}

/* ═══ Inputs ═════════════════════════════════════════════════════════════════ */
QLineEdit, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 13px;
    color: {p['text']};
    selection-background-color: {p['primary_hl']};
    selection-color: {p['text']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 2px solid {p['primary']};
    background-color: {p['surface_2']};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    background-color: {p['surface']};
    color: {p['text_faint']};
    border-color: {p['border_soft']};
}}
QLineEdit:hover:!focus, QSpinBox:hover:!focus, QComboBox:hover:!focus {{
    border-color: {p['text_muted']};
}}

/* ═══ ComboBox ══════════════════════════════════════════════════════════════ */
QComboBox::drop-down {{
    border: none;
    padding-right: 10px;
    width: 20px;
}}
QComboBox::down-arrow {{
    width: 10px;
    height: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: {p['surface_2']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    selection-background-color: {p['primary_hl']};
    selection-color: {p['text']};
    color: {p['text']};
    padding: 4px;
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: 6px 10px;
    border-radius: 4px;
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: {p['surface_hover']};
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

/* ═══ Botones ════════════════════════════════════════════════════════════════ */
QPushButton {{
    background-color: {p['primary']};
    color: {p['text_inverse']};
    border: none;
    border-radius: 6px;
    padding: 9px 20px;
    font-weight: 600;
    font-size: 13px;
    letter-spacing: 0.2px;
}}
QPushButton:hover   {{ background-color: {p['primary_h']}; }}
QPushButton:pressed {{ background-color: {p['primary_a']}; }}
QPushButton:disabled {{
    background-color: {p['surface_3']};
    color: {p['text_faint']};
}}

/* Peligro */
QPushButton[danger="true"] {{
    background-color: {p['danger']};
    color: #ffffff;
}}
QPushButton[danger="true"]:hover   {{ background-color: {p['danger_h']}; }}
QPushButton[danger="true"]:pressed {{ background-color: {p['danger_a']}; }}

/* Secundario (ghost) */
QPushButton[secondary="true"] {{
    background-color: transparent;
    color: {p['primary']};
    border: 1.5px solid {p['primary']};
}}
QPushButton[secondary="true"]:hover {{
    background-color: {p['primary']};
    color: {p['text_inverse']};
}}
QPushButton[secondary="true"]:pressed {{
    background-color: {p['primary_h']};
    color: {p['text_inverse']};
}}
QPushButton[secondary="true"]:disabled {{
    background-color: transparent;
    color: {p['text_faint']};
    border-color: {p['border_soft']};
}}

/* Ghost sin borde */
QPushButton[ghost="true"] {{
    background-color: transparent;
    color: {p['text_muted']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton[ghost="true"]:hover {{
    background-color: {p['surface_2']};
    color: {p['text']};
    border-color: {p['primary']};
}}
QPushButton[ghost="true"]:pressed {{
    background-color: {p['primary_hl']};
}}

/* ═══ Lista de guardados ═════════════════════════════════════════════════════ */
QListWidget {{
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 10px;
    padding: 6px;
    outline: none;
}}
QListWidget::item {{
    border-radius: 7px;
    padding: 10px 14px;
    margin: 2px 0;
    color: {p['text']};
    border: 1px solid transparent;
}}
QListWidget::item:hover {{
    background-color: {p['surface_hover']};
    border: 1px solid {p['border_soft']};
}}
QListWidget::item:selected {{
    background-color: {p['primary_soft']};
    border: 1px solid {p['primary_hl']};
    color: {p['text']};
}}

/* ═══ Panel activo ═══════════════════════════════════════════════════════════ */
QFrame#panelActivo {{
    background-color: {p['primary_soft']};
    border: 2px solid {p['primary_hl']};
    border-radius: 12px;
}}

/* ═══ Panel vacío ════════════════════════════════════════════════════════════ */
QFrame#panelVacio {{
    background-color: {p['surface']};
    border: 2px dashed {p['border']};
    border-radius: 12px;
}}

/* ═══ Separadores ════════════════════════════════════════════════════════════ */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {p['border']};
    max-height: 1px;
    border: none;
    background-color: {p['border']};
}}

/* ═══ Labels especiales ══════════════════════════════════════════════════════ */
QLabel#seccion {{
    font-size: 11px;
    font-weight: 700;
    color: {p['text_faint']};
    letter-spacing: 1.5px;
}}
QLabel#nombreActivo {{
    font-size: 14px;
    font-weight: 600;
    color: {p['text']};
}}
QLabel#fechaItem {{
    font-size: 11px;
    color: {p['text_muted']};
}}
QLabel#appTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {p['text']};
    letter-spacing: -0.3px;
}}

/* ═══ Status bar ════════════════════════════════════════════════════════════ */
QStatusBar {{
    background-color: {p['statusbar_bg']};
    border-top: 1px solid {p['border']};
    font-size: 12px;
    color: {p['text_muted']};
    padding: 3px 10px;
}}

/* ═══ Message Box ════════════════════════════════════════════════════════════ */
QMessageBox {{
    background-color: {p['bg']};
}}
QMessageBox QLabel {{
    color: {p['text']};
    font-size: 13px;
}}
QMessageBox QPushButton {{
    min-width: 80px;
    min-height: 32px;
}}

/* ═══ ToolTip ════════════════════════════════════════════════════════════════ */
QToolTip {{
    background-color: {p['surface_3']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 5px;
    padding: 5px 8px;
    font-size: 12px;
}}
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  Aplicar tema
# ═══════════════════════════════════════════════════════════════════════════════

def apply_theme(app: QApplication, mode: str = "light") -> None:
    """
    Aplica el tema 'light' o 'dark' a toda la aplicación.
    Actualiza el estado global THEME para que los módulos
    puedan leer la paleta activa.
    """
    global THEME, _current_mode
    _current_mode = mode
    palette = LIGHT if mode == "light" else DARK
    THEME.clear()
    THEME.update(palette)

    app.setStyleSheet(_build_stylesheet(palette))

    # Forzar QFont base seguro (siempre >= 1pt)
    base_font = QFont("Segoe UI", font_pt(10))
    app.setFont(base_font)
