"""
modules/settings.py
============================================================
Diálogo de Ajustes — correo emisor y actualizaciones.

Notas
-----
* No usa QFormLayout.removeRow() (crasheaba en varias versiones de
  PyQt6): la fila de contraseña se construye como contenedor desde
  el inicio.
* La contraseña SMTP se guarda en texto plano en config.json y, hoy,
  ningún flujo la usa: el envío se hace abriendo el cliente de correo
  del sistema (mailto:). Por eso el campo es opcional y está avisado
  en la interfaz. Ver README → "Sobre las credenciales".
* Todo el estilo viene del tema; el diálogo entra en un scroll para
  no recortarse en pantallas bajas.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from modules.setup import guardar_config
from modules.theme import SIZE, SPACE
from modules.ui import (
    AreaScroll,
    Aviso,
    FilaAdaptable,
    boton,
    boton_icono,
    etiqueta,
    separador,
)
from modules.version import __version__

SMTP_PRESETS = {
    "Gmail":             ("smtp.gmail.com",       587),
    "Outlook / Hotmail": ("smtp.office365.com",   587),
    "Yahoo Mail":        ("smtp.mail.yahoo.com",  587),
    "Zoho Mail":         ("smtp.zoho.com",        587),
    "Personalizado":     (None,                   None),
}


class DialogoAjustes(QDialog):
    """Ventana modal de ajustes. Lee y escribe config.json."""

    # La ventana principal es la que sabe buscar actualizaciones; el
    # diálogo sólo pide que lo haga.
    buscar_actualizaciones = pyqtSignal()

    def __init__(self, config_path: Path, config: dict, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.config = dict(config)

        self.setWindowTitle("Ajustes")
        self.setObjectName("pantalla")
        # Mínimo chico (entra en pantallas bajas gracias al scroll) pero
        # tamaño inicial cómodo, que muestra el formulario completo.
        self.setMinimumWidth(400)
        self.setMinimumHeight(360)
        self.resize(500, 660)
        self.setModal(True)
        self._build_ui()
        self._cargar_valores()

    # ── Build ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        area = AreaScroll(
            margenes=(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["md"]),
            spacing=SPACE["sm"],
        )
        root = area.lay

        # Encabezado
        root.addWidget(etiqueta("Ajustes", rol="titulo"))
        root.addWidget(etiqueta(
            "Cuenta de correo emisor y preferencias de la aplicación.",
            rol="hint", wrap=True))
        root.addSpacing(SPACE["sm"])
        root.addWidget(separador())
        root.addSpacing(SPACE["sm"])

        # Proveedor SMTP
        root.addWidget(etiqueta("PROVEEDOR SMTP", rol="seccion"))
        self.combo_proveedor = QComboBox()
        self.combo_proveedor.setMinimumHeight(SIZE["input"])
        self.combo_proveedor.addItems(list(SMTP_PRESETS.keys()))
        self.combo_proveedor.currentTextChanged.connect(self._on_proveedor_cambiado)
        root.addWidget(self.combo_proveedor)
        root.addWidget(etiqueta(
            "Elegí un proveedor para autocompletar servidor y puerto, "
            "o 'Personalizado' para ingresarlos a mano.", rol="hint", wrap=True))
        root.addSpacing(SPACE["md"])
        root.addWidget(separador())
        root.addSpacing(SPACE["sm"])

        # Credenciales
        root.addWidget(etiqueta("CREDENCIALES", rol="seccion"))

        form_creds = QFormLayout()
        form_creds.setSpacing(SPACE["sm"])
        form_creds.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_creds.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.input_email = QLineEdit()
        self.input_email.setMinimumHeight(SIZE["input"])
        self.input_email.setPlaceholderText("tu_correo@dominio.com")
        self.input_email.setClearButtonEnabled(True)
        form_creds.addRow("Correo emisor:", self.input_email)

        self.input_password = QLineEdit()
        self.input_password.setMinimumHeight(SIZE["input"])
        self.input_password.setPlaceholderText("Contraseña de aplicación (opcional)")
        self.input_password.setEchoMode(QLineEdit.EchoMode.Password)

        self.btn_toggle_pass = boton_icono(
            "ojo", tooltip="Mostrar / ocultar contraseña", lado=SIZE["input"],
            checkable=True)
        self.btn_toggle_pass.toggled.connect(self._toggle_password)

        contenedor_pass = QWidget()
        lay_pass = QHBoxLayout(contenedor_pass)
        lay_pass.setContentsMargins(0, 0, 0, 0)
        lay_pass.setSpacing(SPACE["xs"])
        lay_pass.addWidget(self.input_password, 1)
        lay_pass.addWidget(self.btn_toggle_pass)
        form_creds.addRow("Contraseña:", contenedor_pass)
        root.addLayout(form_creds)

        root.addWidget(Aviso(
            "La contraseña se guarda en texto plano en config.json y hoy "
            "ningún envío la usa (el correo se abre en tu cliente por mailto:). "
            "Podés dejarla vacía.", tono="warn"))
        root.addSpacing(SPACE["md"])
        root.addWidget(separador())
        root.addSpacing(SPACE["sm"])

        # Actualizaciones
        root.addWidget(etiqueta("ACTUALIZACIONES", rol="seccion"))
        self.chk_actualizaciones = QCheckBox(
            "Avisarme cuando haya una versión nueva")
        self.chk_actualizaciones.setToolTip(
            "Consulta una vez por día si hay una versión publicada.\n"
            "Nunca instala nada sin tu confirmación.")
        root.addWidget(self.chk_actualizaciones)

        fila_upd = QHBoxLayout()
        fila_upd.setSpacing(SPACE["sm"])
        fila_upd.addWidget(etiqueta(f"Versión instalada: {__version__}", rol="hint"))
        fila_upd.addStretch()
        fila_upd.addWidget(boton("Buscar ahora", variant="ghost",
                                 height=SIZE["btn_sm"], compacto=True,
                                 on_click=self._buscar_ahora))
        root.addLayout(fila_upd)
        root.addSpacing(SPACE["md"])
        root.addWidget(separador())
        root.addSpacing(SPACE["sm"])

        # Servidor SMTP
        root.addWidget(etiqueta("SERVIDOR SMTP", rol="seccion"))
        form_smtp = QFormLayout()
        form_smtp.setSpacing(SPACE["sm"])
        form_smtp.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_smtp.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.input_servidor = QLineEdit()
        self.input_servidor.setMinimumHeight(SIZE["input"])
        self.input_servidor.setPlaceholderText("smtp.gmail.com")
        form_smtp.addRow("Servidor SMTP:", self.input_servidor)

        self.spin_puerto = QSpinBox()
        self.spin_puerto.setMinimumHeight(SIZE["input"])
        self.spin_puerto.setRange(1, 65535)
        self.spin_puerto.setValue(587)
        self.spin_puerto.setFixedWidth(110)
        form_smtp.addRow("Puerto:", self.spin_puerto)
        root.addLayout(form_smtp)
        root.addStretch()

        raiz.addWidget(area, 1)

        # Botones (se apilan en diálogos angostos)
        pie = QWidget()
        lay_pie = QVBoxLayout(pie)
        lay_pie.setContentsMargins(SPACE["xl"], SPACE["sm"], SPACE["xl"], SPACE["lg"])
        acciones = FilaAdaptable(breakpoint_px=360, spacing=SPACE["sm"])
        acciones.agregar(boton("Cancelar", variant="secondary",
                               on_click=self.reject))
        acciones.agregar_stretch()
        acciones.agregar(boton("Guardar ajustes", icono="guardar",
                               height=SIZE["btn_lg"],
                               min_w=160, on_click=self._guardar))
        lay_pie.addWidget(acciones)
        raiz.addWidget(pie)

    # ── Helpers internos ──────────────────────────────────────────────────
    def _buscar_ahora(self):
        # Guardamos primero para que el interruptor recién tocado valga ya
        self.config["actualizaciones_automaticas"] = \
            self.chk_actualizaciones.isChecked()
        self.buscar_actualizaciones.emit()

    def _toggle_password(self, visible: bool):
        self.input_password.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)

    def _cargar_valores(self):
        self.chk_actualizaciones.setChecked(
            bool(self.config.get("actualizaciones_automaticas", True)))
        self.input_email.setText(self.config.get("email_user", ""))
        self.input_password.setText(self.config.get("email_password", ""))

        servidor = self.config.get("smtp_server", "smtp.gmail.com")
        try:
            puerto = int(self.config.get("smtp_port", 587))
        except (TypeError, ValueError):
            puerto = 587

        self.input_servidor.setText(servidor)
        self.spin_puerto.setValue(max(1, min(65535, puerto)))

        preset = "Personalizado"
        for nombre, (srv, _) in SMTP_PRESETS.items():
            if srv and srv == servidor:
                preset = nombre
                break

        self.combo_proveedor.blockSignals(True)
        idx = self.combo_proveedor.findText(preset)
        if idx >= 0:
            self.combo_proveedor.setCurrentIndex(idx)
        self.combo_proveedor.blockSignals(False)
        self._on_proveedor_cambiado(preset)

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
        email = self.input_email.text().strip()
        servidor = self.input_servidor.text().strip()

        if not email:
            QMessageBox.warning(self, "Campo requerido",
                                "El correo emisor no puede estar vacío.")
            self.input_email.setFocus()
            return
        if "@" not in email or "." not in email.split("@")[-1]:
            QMessageBox.warning(self, "Correo inválido",
                                "Ingresá un correo válido (ej: cuenta@gmail.com).")
            self.input_email.setFocus()
            return
        if not servidor:
            QMessageBox.warning(self, "Campo requerido",
                                "El servidor SMTP no puede estar vacío.")
            self.input_servidor.setFocus()
            return

        self.config["actualizaciones_automaticas"] = \
            self.chk_actualizaciones.isChecked()
        self.config["email_user"] = email
        self.config["email_password"] = self.input_password.text()
        self.config["smtp_server"] = servidor
        self.config["smtp_port"] = self.spin_puerto.value()

        try:
            guardar_config(self.config, self.config_path)
        except OSError as e:
            QMessageBox.critical(self, "Error al guardar",
                                 f"No se pudo escribir config.json:\n{e}")
            return

        self.accept()
