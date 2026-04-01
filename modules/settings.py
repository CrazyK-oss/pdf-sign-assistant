"""
modules/settings.py
============================================================
Diálogo de Ajustes — configuración del correo emisor.
Usa PyQt6 nativo y hereda el tema activo vía modules.theme.

Fix aplicado: eliminado QFormLayout.removeRow() que causaba crash
en varias versiones de PyQt6. La fila de contraseña se construye
como QWidget contenedor desde el inicio, sin removeRow().
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

from modules.theme import THEME, font_pt


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
    lbl.setObjectName("seccion")
    return lbl


def _lbl_hint(texto: str) -> QLabel:
    lbl = QLabel(texto)
    lbl.setStyleSheet(f"font-size: {font_pt(11)}px; color: {THEME['text_muted']};")
    lbl.setWordWrap(True)
    return lbl


def _ghost_btn(texto: str, fixed_w: int = 0) -> QPushButton:
    b = QPushButton(texto)
    b.setProperty("ghost", "true")
    b.style().unpolish(b)
    b.style().polish(b)
    if fixed_w:
        b.setFixedWidth(fixed_w)
    return b


def _secondary_btn(texto: str) -> QPushButton:
    b = QPushButton(texto)
    b.setProperty("secondary", "true")
    b.style().unpolish(b)
    b.style().polish(b)
    return b


# ── Diálogo principal ─────────────────────────────────────────────────────────

class DialogoAjustes(QDialog):
    """
    Ventana modal de ajustes del correo emisor.
    Lee y escribe directamente en config.json.
    """

    def __init__(self, config_path: Path, config: dict, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.config = dict(config)

        self.setWindowTitle("Ajustes — Correo Emisor")
        self.setMinimumWidth(500)
        self.setModal(True)
        self._build_ui()
        self._cargar_valores()

    # ── Build ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(0)

        # Encabezado
        lbl_titulo = QLabel("Ajustes de correo")
        lbl_titulo.setFont(QFont("Segoe UI", font_pt(15), QFont.Weight.Bold))
        root.addWidget(lbl_titulo)
        root.addSpacing(4)
        root.addWidget(_lbl_hint(
            "Configurá la cuenta desde la cual se envían los documentos firmados."
        ))
        root.addSpacing(14)
        root.addWidget(_sep())
        root.addSpacing(16)

        # Proveedor SMTP
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

        # Credenciales
        root.addWidget(_lbl_seccion("CREDENCIALES"))
        root.addSpacing(10)

        form_creds = QFormLayout()
        form_creds.setSpacing(10)
        form_creds.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Correo
        self.input_email = QLineEdit()
        self.input_email.setPlaceholderText("tu_correo@dominio.com")
        form_creds.addRow("Correo emisor:", self.input_email)

        # Contraseña — contenedor con toggle (sin removeRow)
        self.input_password = QLineEdit()
        self.input_password.setPlaceholderText("Contraseña de aplicación")
        self.input_password.setEchoMode(QLineEdit.EchoMode.Password)

        self.btn_toggle_pass = _ghost_btn("👁", fixed_w=38)
        self.btn_toggle_pass.setFixedHeight(38)
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
            "Activala en Google → Seguridad → Verificación en 2 pasos → Contraseñas de app."
        ))
        root.addSpacing(16)
        root.addWidget(_sep())
        root.addSpacing(16)

        # Servidor SMTP
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
        self.spin_puerto.setFixedWidth(110)
        form_smtp.addRow("Puerto:", self.spin_puerto)

        root.addLayout(form_smtp)
        root.addSpacing(22)
        root.addWidget(_sep())
        root.addSpacing(16)

        # Botones
        fila_btns = QHBoxLayout()
        fila_btns.setSpacing(10)

        btn_cancelar = _secondary_btn("Cancelar")
        btn_cancelar.setMinimumHeight(38)
        btn_cancelar.clicked.connect(self.reject)
        fila_btns.addWidget(btn_cancelar)

        fila_btns.addStretch()

        btn_guardar = QPushButton("💾  Guardar ajustes")
        btn_guardar.setMinimumHeight(42)
        btn_guardar.setMinimumWidth(160)
        btn_guardar.clicked.connect(self._guardar)
        fila_btns.addWidget(btn_guardar)

        root.addLayout(fila_btns)

    # ── Helpers internos ──────────────────────────────────────────────────

    def _toggle_password(self, visible: bool):
        self.input_password.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )

    def _cargar_valores(self):
        self.input_email.setText(self.config.get("email_user", ""))
        self.input_password.setText(self.config.get("email_password", ""))

        servidor = self.config.get("smtp_server", "smtp.gmail.com")
        puerto   = int(self.config.get("smtp_port", 587))
        self.input_servidor.setText(servidor)
        self.spin_puerto.setValue(puerto)

        preset_detectado = "Personalizado"
        for nombre, (srv, _) in SMTP_PRESETS.items():
            if srv and srv == servidor:
                preset_detectado = nombre
                break

        self.combo_proveedor.blockSignals(True)
        idx = self.combo_proveedor.findText(preset_detectado)
        if idx >= 0:
            self.combo_proveedor.setCurrentIndex(idx)
        self.combo_proveedor.blockSignals(False)
        self._on_proveedor_cambiado(preset_detectado)

    def _on_proveedor_cambiado(self, nombre: str):
        servidor, puerto = SMTP_PRESETS.get(nombre, (None, None))
        es_custom = (nombre == "Personalizado")
        self.input_servidor.setEnabled(es_custom)
        self.spin_puerto.setEnabled(es_custom)
        if servidor:
            self.input_servidor.setText(servidor)
        if puerto:
            self.spin_puerto.setValue(puerto)

    # ── Guardar ───────────────────────────────────────────────────────────

    def _guardar(self):
        email    = self.input_email.text().strip()
        password = self.input_password.text()
        servidor = self.input_servidor.text().strip()
        puerto   = self.spin_puerto.value()

        if not email:
            QMessageBox.warning(self, "Campo requerido", "El correo emisor no puede estar vacío.")
            self.input_email.setFocus()
            return
        if "@" not in email or "." not in email:
            QMessageBox.warning(self, "Correo inválido", "Ingresá un correo válido (ej: cuenta@gmail.com).")
            self.input_email.setFocus()
            return
        if not password:
            QMessageBox.warning(self, "Campo requerido", "La contraseña no puede estar vacía.")
            self.input_password.setFocus()
            return
        if not servidor:
            QMessageBox.warning(self, "Campo requerido", "El servidor SMTP no puede estar vacío.")
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
            QMessageBox.critical(self, "Error al guardar", f"No se pudo escribir config.json:\n{e}")
            return

        self.accept()
