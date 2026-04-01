"""
modules/settings.py
============================================================
Diálogo de Ajustes — configuración del correo emisor.
Usa PyQt6 nativo (sin PySimpleGUI) para mantener consistencia
visual con el resto de la aplicación.

Fix: eliminado el uso de QFormLayout.removeRow() que causaba un crash
al abrir el diálogo en varias versiones de PyQt6. La fila de contraseña
ahora se construye directamente como un QWidget contenedor.
"""

import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QSpinBox, QComboBox, QMessageBox,
    QFormLayout, QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


# ── Paleta ──────────────────────────────────────────────────────────────────────
C_BG          = "#f7f6f2"
C_SURFACE     = "#f3f0ec"
C_SURFACE_2   = "#edeae5"
C_BORDER      = "#d4d1ca"
C_BORDER_SOFT = "#e0ddd7"
C_TEXT        = "#28251d"
C_MUTED       = "#7a7974"
C_FAINT       = "#bab9b4"
C_PRIMARY     = "#01696f"
C_PRIMARY_H   = "#0c4e54"
C_PRIMARY_A   = "#0f3638"
C_PRIMARY_HL  = "#cedcd8"
C_DANGER      = "#a13544"
C_DANGER_H    = "#782b33"
C_SUCCESS_BG  = "#d4dfcc"
C_SUCCESS     = "#437a22"


STYLESHEET_SETTINGS = f"""
QDialog, QWidget {{
    background-color: {C_BG};
    color: {C_TEXT};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}
QLineEdit, QSpinBox, QComboBox {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 13px;
    color: {C_TEXT};
    selection-background-color: {C_PRIMARY_HL};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1.5px solid {C_PRIMARY};
    background-color: white;
}}
QLineEdit:disabled, QSpinBox:disabled {{
    background-color: {C_SURFACE_2};
    color: {C_FAINT};
}}
QComboBox::drop-down {{
    border: none;
    padding-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER};
    selection-background-color: {C_PRIMARY_HL};
    color: {C_TEXT};
}}
QPushButton {{
    background-color: {C_PRIMARY};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton:hover   {{ background-color: {C_PRIMARY_H}; }}
QPushButton:pressed {{ background-color: {C_PRIMARY_A}; }}
QPushButton:disabled {{
    background-color: {C_BORDER};
    color: {C_MUTED};
}}
QPushButton[secondary="true"] {{
    background-color: transparent;
    color: {C_PRIMARY};
    border: 1.5px solid {C_PRIMARY};
}}
QPushButton[secondary="true"]:hover {{
    background-color: {C_PRIMARY};
    color: white;
}}
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {C_BORDER};
    max-height: 1px;
}}
"""


SMTP_PRESETS = {
    "Gmail":             ("smtp.gmail.com",       587),
    "Outlook / Hotmail": ("smtp.office365.com",   587),
    "Yahoo Mail":        ("smtp.mail.yahoo.com",  587),
    "Zoho Mail":         ("smtp.zoho.com",        587),
    "Personalizado":     (None,                   None),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sep() -> QFrame:
    s = QFrame()
    s.setFrameShape(QFrame.Shape.HLine)
    s.setFrameShadow(QFrame.Shadow.Plain)
    return s


def _lbl_seccion(texto: str) -> QLabel:
    lbl = QLabel(texto)
    lbl.setStyleSheet(
        f"font-size: 11px; font-weight: 700; color: {C_MUTED}; letter-spacing: 1px;"
    )
    return lbl


def _lbl_hint(texto: str) -> QLabel:
    lbl = QLabel(texto)
    lbl.setStyleSheet(f"font-size: 11px; color: {C_MUTED};")
    lbl.setWordWrap(True)
    return lbl


def _secondary_btn(texto: str, ancho_fijo: int = 0) -> QPushButton:
    b = QPushButton(texto)
    b.setProperty("secondary", "true")
    b.style().unpolish(b)
    b.style().polish(b)
    if ancho_fijo:
        b.setFixedWidth(ancho_fijo)
    return b


# ── Diálogo principal ──────────────────────────────────────────────────────────

class DialogoAjustes(QDialog):
    """
    Ventana modal de ajustes del correo emisor.
    Lee y escribe directamente en config.json.
    """

    def __init__(self, config_path: Path, config: dict, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.config = dict(config)          # copia local para no mutar el original

        self.setWindowTitle("Ajustes — Correo Emisor")
        self.setMinimumWidth(500)
        self.setModal(True)
        self.setStyleSheet(STYLESHEET_SETTINGS)

        self._build_ui()
        self._cargar_valores()

    # ── Construcción de UI ────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(0)

        # ── Encabezado ──
        lbl_titulo = QLabel("⚙️  Ajustes de correo")
        lbl_titulo.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        root.addWidget(lbl_titulo)
        root.addSpacing(4)
        root.addWidget(_lbl_hint(
            "Configurá la cuenta desde la cual se envían los documentos firmados."
        ))
        root.addSpacing(14)
        root.addWidget(_sep())
        root.addSpacing(16)

        # ── Proveedor SMTP ──
        root.addWidget(_lbl_seccion("PROVEEDOR SMTP"))
        root.addSpacing(8)
        self.combo_proveedor = QComboBox()
        self.combo_proveedor.addItems(list(SMTP_PRESETS.keys()))
        self.combo_proveedor.currentTextChanged.connect(self._on_proveedor_cambiado)
        root.addWidget(self.combo_proveedor)
        root.addSpacing(4)
        root.addWidget(_lbl_hint(
            "Elegí un proveedor para autocompletar servidor y puerto, "
            "o 'Personalizado' para ingresarlos manualmente."
        ))
        root.addSpacing(16)
        root.addWidget(_sep())
        root.addSpacing(16)

        # ── Credenciales ──
        root.addWidget(_lbl_seccion("CREDENCIALES"))
        root.addSpacing(10)

        form_creds = QFormLayout()
        form_creds.setSpacing(10)
        form_creds.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Correo
        self.input_email = QLineEdit()
        self.input_email.setPlaceholderText("tu_correo@dominio.com")
        form_creds.addRow("Correo emisor:", self.input_email)

        # Contraseña — widget contenedor con toggle (sin removeRow)
        self.input_password = QLineEdit()
        self.input_password.setPlaceholderText("Contraseña de aplicación")
        self.input_password.setEchoMode(QLineEdit.EchoMode.Password)

        self.btn_toggle_pass = _secondary_btn("👁", ancho_fijo=36)
        self.btn_toggle_pass.setFixedHeight(36)
        self.btn_toggle_pass.setCheckable(True)
        self.btn_toggle_pass.setToolTip("Mostrar / ocultar contraseña")
        self.btn_toggle_pass.toggled.connect(self._toggle_password)

        contenedor_pass = QWidget()
        contenedor_pass.setStyleSheet("background: transparent;")
        lay_pass = QHBoxLayout(contenedor_pass)
        lay_pass.setContentsMargins(0, 0, 0, 0)
        lay_pass.setSpacing(6)
        lay_pass.addWidget(self.input_password)
        lay_pass.addWidget(self.btn_toggle_pass)

        form_creds.addRow("Contraseña:", contenedor_pass)

        root.addLayout(form_creds)
        root.addSpacing(6)
        root.addWidget(_lbl_hint(
            "Para Gmail: usá una Contraseña de Aplicación, no tu contraseña normal. "
            "Activála en Google → Seguridad → Verificación en 2 pasos → Contraseñas de app."
        ))
        root.addSpacing(16)
        root.addWidget(_sep())
        root.addSpacing(16)

        # ── Servidor SMTP ──
        root.addWidget(_lbl_seccion("SERVIDOR SMTP"))
        root.addSpacing(10)

        form_smtp = QFormLayout()
        form_smtp.setSpacing(10)
        form_smtp.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.input_servidor = QLineEdit()
        self.input_servidor.setPlaceholderText("smtp.gmail.com")
        form_smtp.addRow("Servidor SMTP:", self.input_servidor)

        self.spin_puerto = QSpinBox()
        self.spin_puerto.setRange(1, 65535)
        self.spin_puerto.setValue(587)
        self.spin_puerto.setFixedWidth(100)
        form_smtp.addRow("Puerto:", self.spin_puerto)

        root.addLayout(form_smtp)
        root.addSpacing(20)
        root.addWidget(_sep())
        root.addSpacing(16)

        # ── Botones ──
        fila_btns = QHBoxLayout()
        fila_btns.setSpacing(8)

        btn_cancelar = _secondary_btn("Cancelar")
        btn_cancelar.setMinimumHeight(36)
        btn_cancelar.clicked.connect(self.reject)
        fila_btns.addWidget(btn_cancelar)

        fila_btns.addStretch()

        btn_guardar = QPushButton("💾  Guardar ajustes")
        btn_guardar.setMinimumHeight(40)
        btn_guardar.setMinimumWidth(160)
        btn_guardar.clicked.connect(self._guardar)
        fila_btns.addWidget(btn_guardar)

        root.addLayout(fila_btns)

    # ── Toggle contraseña ──────────────────────────────────────────────────

    def _toggle_password(self, visible: bool):
        self.input_password.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )

    # ── Cargar valores desde config ─────────────────────────────────────────

    def _cargar_valores(self):
        """Rellena los campos con los valores actuales de config."""
        self.input_email.setText(self.config.get("email_user", ""))
        self.input_password.setText(self.config.get("email_password", ""))

        servidor = self.config.get("smtp_server", "smtp.gmail.com")
        puerto   = int(self.config.get("smtp_port", 587))

        self.input_servidor.setText(servidor)
        self.spin_puerto.setValue(puerto)

        # Detectar preset por servidor guardado
        preset_detectado = "Personalizado"
        for nombre, (srv, _) in SMTP_PRESETS.items():
            if srv and srv == servidor:
                preset_detectado = nombre
                break

        # Bloquear la señal mientras seteamos el combo para evitar doble disparo
        self.combo_proveedor.blockSignals(True)
        idx = self.combo_proveedor.findText(preset_detectado)
        if idx >= 0:
            self.combo_proveedor.setCurrentIndex(idx)
        self.combo_proveedor.blockSignals(False)

        # Aplicar estado de bloqueo manualmente
        self._on_proveedor_cambiado(preset_detectado)

    # ── Cambio de proveedor ────────────────────────────────────────────────

    def _on_proveedor_cambiado(self, nombre: str):
        """Autocompletea servidor/puerto según el preset elegido."""
        servidor, puerto = SMTP_PRESETS.get(nombre, (None, None))
        es_personalizado = (nombre == "Personalizado")

        self.input_servidor.setEnabled(es_personalizado)
        self.spin_puerto.setEnabled(es_personalizado)

        if servidor:
            self.input_servidor.setText(servidor)
        if puerto:
            self.spin_puerto.setValue(puerto)

    # ── Guardar ─────────────────────────────────────────────────────────────────

    def _guardar(self):
        email    = self.input_email.text().strip()
        password = self.input_password.text()
        servidor = self.input_servidor.text().strip()
        puerto   = self.spin_puerto.value()

        if not email:
            QMessageBox.warning(self, "Campo requerido",
                                "El correo emisor no puede estar vacío.")
            self.input_email.setFocus()
            return
        if "@" not in email or "." not in email:
            QMessageBox.warning(self, "Correo inválido",
                                "Ingresá un correo válido (ej: cuenta@gmail.com).")
            self.input_email.setFocus()
            return
        if not password:
            QMessageBox.warning(self, "Campo requerido",
                                "La contraseña no puede estar vacía.")
            self.input_password.setFocus()
            return
        if not servidor:
            QMessageBox.warning(self, "Campo requerido",
                                "El servidor SMTP no puede estar vacío.")
            self.input_servidor.setFocus()
            return

        self.config["email_user"]     = email
        self.config["email_password"] = password
        self.config["smtp_server"]    = servidor
        self.config["smtp_port"]      = puerto

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, "Error al guardar",
                                 f"No se pudo escribir config.json:\n{e}")
            return

        self.accept()
