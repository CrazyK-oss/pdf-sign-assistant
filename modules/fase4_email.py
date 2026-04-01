"""
modules/fase4_email.py
============================================================
Fase 4 – Enviar el PDF firmado por correo.

Estrategia:
  1. El usuario escribe el destinatario y confirma.
  2. Se abre Outlook (o el cliente predeterminado) con:
       - Para: destinatario
       - Asunto rellenado
       - El PDF adjuntado automáticamente vía win32com.client
         (Outlook COM). Si COM falla o no es Windows, se abre
         un mailto: simple sin adjunto.

Dependencias:
    pywin32  (pip install pywin32)  – ya requerido por fase2_print
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTextEdit,
    QVBoxLayout,
)


# ── Paleta ───────────────────────────────────────────────────────────────────
C_BG        = "#f7f6f2"
C_SURFACE   = "#f3f0ec"
C_BORDER    = "#d4d1ca"
C_TEXT      = "#28251d"
C_MUTED     = "#7a7974"
C_PRIMARY   = "#01696f"
C_PRIMARY_H = "#0c4e54"
C_PRIMARY_A = "#0f3638"
C_FAINT     = "#bab9b4"
C_ERROR_TXT = "#a13544"

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

# ── Helpers ───────────────────────────────────────────────────────────────────
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


# ── Lógica de apertura del cliente de correo ──────────────────────────────

def _abrir_outlook_com(destinatario: str, asunto: str,
                       cuerpo: str, pdf_path: Path) -> bool:
    """
    Abre un borrador de Outlook con el PDF adjuntado usando la API COM.
    Devuelve True si tuvo éxito.
    """
    try:
        import win32com.client  # parte de pywin32
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail    = outlook.CreateItem(0)  # 0 = MailItem
        mail.To      = destinatario
        mail.Subject = asunto
        mail.Body    = cuerpo
        mail.Attachments.Add(str(pdf_path.resolve()))
        mail.Display(True)   # True = modal (espera al usuario)
        return True
    except Exception as e:
        print(f"[FASE 4] Outlook COM falló ({e}), fallback a mailto:")
        return False


def _abrir_mailto(destinatario: str, asunto: str) -> None:
    """
    Fallback: abre el cliente de correo predeterminado vía mailto:.
    No puede adjuntar archivos (limitación del protocolo).
    """
    uri = f"mailto:{quote(destinatario)}?subject={quote(asunto)}"
    if sys.platform == "win32":
        os.startfile(uri)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", uri])


def _enviar_con_cliente(
    destinatario: str, pdf_path: Path, nombre_doc: str
) -> str | None:
    """
    Intenta abrir Outlook vía COM con el adjunto.
    Devuelve None si fue exitoso, o un mensaje de aviso si se usó fallback.
    """
    asunto = f"Documento Firmado: {nombre_doc}"
    cuerpo = (
        f"Estimado/a,\n\n"
        f"Adjunto encontrará el documento '{nombre_doc}' con las páginas firmadas.\n\n"
        f"Este mensaje fue preparado automáticamente por PDF Sign Assistant.\n"
    )

    if sys.platform == "win32":
        ok = _abrir_outlook_com(destinatario, asunto, cuerpo, pdf_path)
        if ok:
            return None  # éxito

    # Fallback mailto: (sin adjunto)
    _abrir_mailto(destinatario, asunto)
    return (
        "Se abrió el cliente de correo predeterminado.\n\n"
        "No se pudo adjuntar el PDF automáticamente "
        "(Outlook no respondio vía COM).\n"
        f"Adjuntá manualmente el archivo:\n{pdf_path}"
    )


# ── Diálogo principal ─────────────────────────────────────────────────────────
class DialogoEnviarEmail(QDialog):

    def __init__(self, pdf_firmado: Path, config: dict,
                 paginas: list, nombre_doc: str, parent=None):
        super().__init__(parent)
        self.pdf_firmado = pdf_firmado
        self.paginas     = paginas
        self.nombre_doc  = nombre_doc

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

        # ─ Título
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

        lbl_sub = QLabel(
            f"Se abrirá Outlook con <b>{self.pdf_firmado.name}</b> adjuntado."
        )
        lbl_sub.setStyleSheet(f"color: {C_MUTED}; font-size: 12px;")
        lbl_sub.setWordWrap(True)
        lay.addWidget(lbl_sub)
        lay.addSpacing(18)
        lay.addWidget(self._sep())
        lay.addSpacing(18)

        # ─ Destinatario
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

        # ─ Resumen
        lbl_resumen_titulo = QLabel("Resumen del documento")
        lbl_resumen_titulo.setStyleSheet("font-weight: 600;")
        lay.addWidget(lbl_resumen_titulo)
        lay.addSpacing(6)

        self.txt_resumen = QTextEdit()
        self.txt_resumen.setReadOnly(True)
        self.txt_resumen.setFixedHeight(82)
        self.txt_resumen.setPlainText(
            _construir_resumen(self.nombre_doc, self.paginas)
        )
        lay.addWidget(self.txt_resumen)
        lay.addSpacing(20)
        lay.addWidget(self._sep())
        lay.addSpacing(14)

        # ─ Nota informativa
        lbl_nota = QLabel(
            "ℹ️  Se abrirá Outlook con el PDF listo para enviar. "
            "Solo tocá <b>Enviar</b> dentro de Outlook."
        )
        lbl_nota.setStyleSheet(f"font-size: 11px; color: {C_MUTED};")
        lbl_nota.setWordWrap(True)
        lay.addWidget(lbl_nota)
        lay.addSpacing(16)

        # ─ Botones
        fila_btns = QHBoxLayout()
        fila_btns.setSpacing(10)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setProperty("secondary", "true")
        btn_cancelar.style().unpolish(btn_cancelar)
        btn_cancelar.style().polish(btn_cancelar)
        btn_cancelar.clicked.connect(self.reject)
        fila_btns.addWidget(btn_cancelar)
        fila_btns.addStretch()

        self.btn_abrir = QPushButton("✉️  Abrir Outlook")
        self.btn_abrir.setMinimumWidth(180)
        self.btn_abrir.setEnabled(False)
        self.btn_abrir.clicked.connect(self._on_abrir)
        fila_btns.addWidget(self.btn_abrir)
        lay.addLayout(fila_btns)

    # ── Validación ────────────────────────────────────────────────────────
    def _on_email_changed(self, texto: str):
        texto = texto.strip()
        if not texto:
            self.lbl_error.setText("")
            self.input_email.setProperty("invalid", "false")
            self.btn_abrir.setEnabled(False)
        elif not _es_email_valido(texto):
            self.lbl_error.setText("Correo inválido (ejemplo: nombre@dominio.com)")
            self.input_email.setProperty("invalid", "true")
            self.btn_abrir.setEnabled(False)
        else:
            self.lbl_error.setText("")
            self.input_email.setProperty("invalid", "false")
            self.btn_abrir.setEnabled(True)
        self.input_email.style().unpolish(self.input_email)
        self.input_email.style().polish(self.input_email)

    # ── Acción principal ──────────────────────────────────────────────────
    def _on_abrir(self):
        destinatario = self.input_email.text().strip()
        if not _es_email_valido(destinatario):
            return

        self.btn_abrir.setText("Abriendo…")
        self.btn_abrir.setEnabled(False)

        aviso = _enviar_con_cliente(
            destinatario=destinatario,
            pdf_path=self.pdf_firmado,
            nombre_doc=self.nombre_doc,
        )

        if aviso:
            QMessageBox.warning(self, "Adjunto manual requerido", aviso)

        self.accept()


# ── API pública ───────────────────────────────────────────────────────────────
def enviar_documento(
    pdf_firmado: Path,
    config: dict,
    paginas: list,
    nombre_doc: str,
    parent=None,
) -> None:
    DialogoEnviarEmail(
        pdf_firmado=pdf_firmado,
        config=config,
        paginas=paginas,
        nombre_doc=nombre_doc,
        parent=parent,
    ).exec()
