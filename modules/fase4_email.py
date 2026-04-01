"""
modules/fase4_email.py
============================================================
Fase 4: Enviar el PDF firmado por correo.

Mejoras en esta versión:
- _SmtpWorker intenta STARTTLS (puerto 587) primero y hace fallback
  automático a SSL implícito (puerto 465) si el primer intento falla.
  Esto soluciona fallos silenciosos en redes con antivirus/proxy que
  bloquean STARTTLS pero permiten SSL directo.
- Timeout extendido a 30 s.
- Mensaje de error más descriptivo con sugerencia de qué revisar.
"""

import re
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTextEdit,
    QVBoxLayout,
)


# ── Paleta ────────────────────────────────────────────────────────────────────
C_BG        = "#f7f6f2"
C_SURFACE   = "#f3f0ec"
C_BORDER    = "#d4d1ca"
C_TEXT      = "#28251d"
C_MUTED     = "#7a7974"
C_PRIMARY   = "#01696f"
C_PRIMARY_H = "#0c4e54"
C_PRIMARY_A = "#0f3638"
C_PRIMARY_HL= "#cedcd8"
C_SUCCESS   = "#437a22"
C_SUCCESS_BG= "#d4dfcc"
C_DANGER    = "#a13544"
C_ERROR_TXT = "#a13544"
C_FAINT     = "#bab9b4"

STYLESHEET_DIALOG = f"""
QDialog, QWidget {{
    background-color: {C_BG};
    color: {C_TEXT};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}
QLineEdit {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 14px;
    color: {C_TEXT};
}}
QLineEdit:focus {{
    border-color: {C_PRIMARY};
    background-color: white;
}}
QLineEdit[invalid="true"] {{
    border-color: {C_ERROR_TXT};
}}
QTextEdit {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 8px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
    color: {C_MUTED};
}}
QPushButton {{
    background-color: {C_PRIMARY};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-weight: 600;
    font-size: 13px;
    min-height: 36px;
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

# ── Validación ────────────────────────────────────────────────────────────────
EMAIL_REGEX = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]{2,}$")


def _es_email_valido(email: str) -> bool:
    return bool(EMAIL_REGEX.match(email.strip()))


def _construir_resumen(nombre_doc: str, paginas: list) -> str:
    nums = ", ".join(str(p + 1) for p in paginas)
    return (
        f"Documento:              {nombre_doc}\n"
        f"Páginas reemplazadas:   {nums}\n"
        f"Total páginas firmadas: {len(paginas)}"
    )


def _construir_mensaje(config: dict, destinatario: str,
                       pdf_path: Path, nombre_doc: str) -> MIMEMultipart:
    """Construye el objeto MIMEMultipart listo para enviar."""
    msg = MIMEMultipart()
    msg["From"]    = config["email_user"]
    msg["To"]      = destinatario
    msg["Subject"] = f"Documento Firmado: {nombre_doc}"

    cuerpo = (
        f"Estimado/a,\n\n"
        f"Adjunto encontrará el documento '{nombre_doc}' "
        f"con las páginas firmadas.\n\n"
        f"Este correo fue generado automáticamente por PDF Sign Assistant.\n"
    )
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

    with open(pdf_path, "rb") as f:
        adjunto = MIMEBase("application", "octet-stream")
        adjunto.set_payload(f.read())
    encoders.encode_base64(adjunto)
    adjunto.add_header(
        "Content-Disposition",
        f'attachment; filename="{pdf_path.name}"',
    )
    msg.attach(adjunto)
    return msg


# ── Worker SMTP ───────────────────────────────────────────────────────────────
class _SmtpWorker(QThread):
    """
    Estrategia de envío (en orden):
      1. STARTTLS en el puerto configurado (por defecto 587).
      2. Si falla con SMTPException/OSError, reintenta con SSL implícito
         en puerto 465 (SMTP_SSL). Esto cubre redes corporativas o antivirus
         que bloquean STARTTLS pero permiten SSL directo.

    Emite resultado(ok: bool, mensaje_error: str).
    """
    resultado = pyqtSignal(bool, str)

    _TIMEOUT = 30  # segundos

    def __init__(self, config: dict, destinatario: str,
                 pdf_path: Path, nombre_doc: str):
        super().__init__()
        self.config       = config
        self.destinatario = destinatario
        self.pdf_path     = pdf_path
        self.nombre_doc   = nombre_doc

    def run(self):
        server   = self.config.get("smtp_server", "smtp.gmail.com")
        port     = int(self.config.get("smtp_port", 587))
        user     = self.config["email_user"]
        password = self.config["email_password"]

        try:
            msg = _construir_mensaje(
                self.config, self.destinatario,
                self.pdf_path, self.nombre_doc,
            )
        except Exception as e:
            self.resultado.emit(False, f"Error al preparar el adjunto:\n{e}")
            return

        # — Intento 1: STARTTLS —
        ultimo_error = None
        try:
            with smtplib.SMTP(server, port, timeout=self._TIMEOUT) as srv:
                srv.ehlo()
                srv.starttls()
                srv.ehlo()
                srv.login(user, password)
                srv.sendmail(user, self.destinatario, msg.as_string())
            print(f"[FASE 4] ✓ Email enviado (STARTTLS) a: {self.destinatario}")
            self.resultado.emit(True, "")
            return
        except smtplib.SMTPAuthenticationError as e:
            # Error de credenciales → no tiene sentido reintentar con SSL
            self.resultado.emit(False, self._msg_auth())
            return
        except (smtplib.SMTPException, OSError, TimeoutError) as e:
            ultimo_error = e
            print(f"[FASE 4] STARTTLS falló ({e}), reintentando con SSL puerto 465…")

        # — Intento 2: SSL implícito en 465 —
        try:
            with smtplib.SMTP_SSL(server, 465, timeout=self._TIMEOUT) as srv:
                srv.ehlo()
                srv.login(user, password)
                srv.sendmail(user, self.destinatario, msg.as_string())
            print(f"[FASE 4] ✓ Email enviado (SSL/465) a: {self.destinatario}")
            self.resultado.emit(True, "")
            return
        except smtplib.SMTPAuthenticationError:
            self.resultado.emit(False, self._msg_auth())
        except (smtplib.SMTPConnectError, OSError):
            self.resultado.emit(
                False,
                f"No se pudo conectar al servidor SMTP '{server}'.\n\n"
                "Verificá:\n"
                "• Servidor y puerto en Ajustes (⚙)\n"
                "• Tu conexión a internet\n"
                "• Que el firewall/antivirus no bloquee el puerto SMTP\n\n"
                f"Error original: {ultimo_error}"
            )
        except TimeoutError:
            self.resultado.emit(
                False,
                "Tiempo de espera agotado al conectar con el servidor SMTP.\n"
                "Verificá tu conexión a internet."
            )
        except Exception as e:
            print(f"[ERROR fase4 smtp] {e}")
            self.resultado.emit(False, f"Error al enviar el correo:\n{e}")

    @staticmethod
    def _msg_auth() -> str:
        return (
            "Error de autenticación SMTP.\n\n"
            "Verificá en Ajustes (⚙):\n"
            "• El correo emisor es correcto\n"
            "• La contraseña es una Contraseña de Aplicación\n"
            "  (para Gmail: Google → Seguridad → "
            "Verificación en 2 pasos → Contraseñas de app)"
        )


# ── Diálogo principal ─────────────────────────────────────────────────────────
class DialogoEnviarEmail(QDialog):

    def __init__(self, pdf_firmado: Path, config: dict,
                 paginas: list, nombre_doc: str, parent=None):
        super().__init__(parent)
        self.pdf_firmado = pdf_firmado
        self.config      = config
        self.paginas     = paginas
        self.nombre_doc  = nombre_doc
        self._worker     = None

        self.setWindowTitle("Enviar documento firmado")
        self.setMinimumWidth(480)
        self.setModal(True)
        self.setStyleSheet(STYLESHEET_DIALOG)
        self._build_ui()

    def _sep(self) -> QFrame:
        s = QFrame()
        s.setFrameShape(QFrame.Shape.HLine)
        s.setFrameShadow(QFrame.Shadow.Plain)
        return s

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(0)

        # Título
        fila_titulo = QHBoxLayout()
        icono = QLabel("✉️")
        icono.setFont(QFont("Segoe UI Emoji", 20))
        fila_titulo.addWidget(icono)
        fila_titulo.addSpacing(10)
        lbl_titulo = QLabel("Enviar por correo")
        lbl_titulo.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        fila_titulo.addWidget(lbl_titulo)
        fila_titulo.addStretch()
        lay.addLayout(fila_titulo)
        lay.addSpacing(4)

        lbl_sub = QLabel(f"Se adjuntará <b>{self.pdf_firmado.name}</b> al correo.")
        lbl_sub.setStyleSheet(f"color: {C_MUTED}; font-size: 12px;")
        lbl_sub.setWordWrap(True)
        lay.addWidget(lbl_sub)
        lay.addSpacing(18)
        lay.addWidget(self._sep())
        lay.addSpacing(18)

        # Destinatario
        lbl_dest = QLabel("Correo destinatario")
        lbl_dest.setStyleSheet("font-weight: 600;")
        lay.addWidget(lbl_dest)
        lay.addSpacing(6)

        self.input_email = QLineEdit()
        self.input_email.setPlaceholderText("ejemplo@dominio.com")
        self.input_email.textChanged.connect(self._on_email_changed)
        lay.addWidget(self.input_email)
        lay.addSpacing(4)

        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet(f"color: {C_ERROR_TXT}; font-size: 11px;")
        lay.addWidget(self.lbl_error)
        lay.addSpacing(16)

        # Resumen
        lbl_resumen_titulo = QLabel("Resumen del documento")
        lbl_resumen_titulo.setStyleSheet("font-weight: 600;")
        lay.addWidget(lbl_resumen_titulo)
        lay.addSpacing(6)

        self.txt_resumen = QTextEdit()
        self.txt_resumen.setReadOnly(True)
        self.txt_resumen.setFixedHeight(82)
        self.txt_resumen.setPlainText(_construir_resumen(self.nombre_doc, self.paginas))
        lay.addWidget(self.txt_resumen)
        lay.addSpacing(20)
        lay.addWidget(self._sep())
        lay.addSpacing(16)

        # Correo emisor
        emisor = self.config.get("email_user", "")
        if emisor:
            lbl_emisor = QLabel(f"📤  Correo emisor: <b>{emisor}</b>")
        else:
            lbl_emisor = QLabel(
                "⚠️  No hay correo emisor configurado.  "
                "<a href='settings'>Ir a Ajustes</a>"
            )
            lbl_emisor.linkActivated.connect(self._pedir_abrir_ajustes)
        lbl_emisor.setStyleSheet(f"font-size: 12px; color: {C_MUTED};")
        lbl_emisor.setWordWrap(True)
        lay.addWidget(lbl_emisor)
        lay.addSpacing(16)

        # Botones
        fila_btns = QHBoxLayout()
        fila_btns.setSpacing(10)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setProperty("secondary", "true")
        btn_cancelar.style().unpolish(btn_cancelar)
        btn_cancelar.style().polish(btn_cancelar)
        btn_cancelar.clicked.connect(self.reject)
        fila_btns.addWidget(btn_cancelar)
        fila_btns.addStretch()

        self.btn_enviar = QPushButton("✉️  Enviar documento")
        self.btn_enviar.setMinimumWidth(180)
        self.btn_enviar.setEnabled(False)
        self.btn_enviar.clicked.connect(self._iniciar_envio)
        fila_btns.addWidget(self.btn_enviar)
        lay.addLayout(fila_btns)

    def _on_email_changed(self, texto: str):
        texto = texto.strip()
        sin_creds = (
            not self.config.get("email_user")
            or not self.config.get("email_password")
        )
        if not texto:
            self.lbl_error.setText("")
            self.input_email.setProperty("invalid", "false")
            self.btn_enviar.setEnabled(False)
        elif not _es_email_valido(texto):
            self.lbl_error.setText("Correo inválido (ejemplo: nombre@dominio.com)")
            self.input_email.setProperty("invalid", "true")
            self.btn_enviar.setEnabled(False)
        elif sin_creds:
            self.lbl_error.setText(
                "Configurá el correo emisor en Ajustes (⚙) antes de enviar."
            )
            self.input_email.setProperty("invalid", "false")
            self.btn_enviar.setEnabled(False)
        else:
            self.lbl_error.setText("")
            self.input_email.setProperty("invalid", "false")
            self.btn_enviar.setEnabled(True)
        self.input_email.style().unpolish(self.input_email)
        self.input_email.style().polish(self.input_email)

    def _iniciar_envio(self):
        destinatario = self.input_email.text().strip()
        if not _es_email_valido(destinatario):
            return
        self.btn_enviar.setText("Enviando…")
        self.btn_enviar.setEnabled(False)
        self.input_email.setEnabled(False)
        self._worker = _SmtpWorker(
            config=self.config,
            destinatario=destinatario,
            pdf_path=self.pdf_firmado,
            nombre_doc=self.nombre_doc,
        )
        self._worker.resultado.connect(self._on_resultado)
        self._worker.start()

    def _on_resultado(self, ok: bool, error: str):
        if ok:
            QMessageBox.information(
                self, "✅ Enviado",
                f"Documento enviado correctamente a:\n{self.input_email.text().strip()}",
            )
            self.accept()
        else:
            QMessageBox.critical(self, "Error al enviar", error)
            self.btn_enviar.setText("✉️  Enviar documento")
            self.btn_enviar.setEnabled(True)
            self.input_email.setEnabled(True)

    def _pedir_abrir_ajustes(self, _link: str):
        QMessageBox.information(
            self, "Ajustes requeridos",
            "Cerrá este diálogo y presioná el botón ⚙ en la ventana principal "
            "para configurar el correo emisor.",
        )


# ── API pública ───────────────────────────────────────────────────────────────
def enviar_documento(
    pdf_firmado: Path,
    config: dict,
    paginas: list,
    nombre_doc: str,
    parent=None,
) -> None:
    dialogo = DialogoEnviarEmail(
        pdf_firmado=pdf_firmado,
        config=config,
        paginas=paginas,
        nombre_doc=nombre_doc,
        parent=parent,
    )
    dialogo.exec()
