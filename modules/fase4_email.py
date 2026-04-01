"""
modules/fase4_email.py
============================================================
Fase 4 – Enviar el PDF firmado por correo.

Estrategia:
  1. El usuario escribe el destinatario y confirma.
  2. Se crea una carpeta temporal _envio_temp/ dentro de pdfs_firmados/
     con únicamente una copia del PDF a enviar.
  3. Se abre esa carpeta en el Explorador (solo ese archivo visible)
     y simultáneamente se abre el cliente de correo predeterminado
     con destinatario, asunto y cuerpo prellenados vía mailto:.
  4. El usuario arrastra el archivo al correo y envía.
  5. Un hilo daemon borra la carpeta _envio_temp/ después de 30 min.
     Adicionalmente, la carpeta se limpia automáticamente al iniciar
     la app (limpiar_temp_al_iniciar).

No requiere pywin32, Outlook ni ningún cliente específico.
"""

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTextEdit,
    QVBoxLayout,
)

# ── Constantes ────────────────────────────────────────────────────────────────
TEMP_FOLDER_NAME  = "_envio_temp"
TEMP_CLEANUP_SECS = 30 * 60  # 30 minutos


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


# ── Gestión de carpeta temporal ───────────────────────────────────────────────

def _carpeta_temp(carpeta_firmados: Path) -> Path:
    return carpeta_firmados / TEMP_FOLDER_NAME


def limpiar_temp_al_iniciar(carpeta_firmados: Path) -> None:
    """
    Llamaá esto al arrancar la app para limpiar restos de sesiones anteriores.
    """
    temp = _carpeta_temp(carpeta_firmados)
    if temp.exists():
        try:
            shutil.rmtree(temp)
        except Exception:
            pass


def _limpiar_temp_delayed(temp: Path, delay_secs: int) -> None:
    """Corre en un hilo daemon: espera delay_secs y borra la carpeta temp."""
    time.sleep(delay_secs)
    try:
        if temp.exists():
            shutil.rmtree(temp)
    except Exception:
        pass


def _preparar_temp(pdf_origen: Path, carpeta_firmados: Path) -> Path:
    """
    Crea _envio_temp/ con solo la copia del PDF y lanza el timer de limpieza.
    Devuelve la ruta de la copia temporal.
    """
    temp = _carpeta_temp(carpeta_firmados)
    # Limpiar si quedó algo de un envio anterior
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True, exist_ok=True)

    destino = temp / pdf_origen.name
    shutil.copy2(pdf_origen, destino)

    # Timer de limpieza automática
    t = threading.Thread(
        target=_limpiar_temp_delayed,
        args=(temp, TEMP_CLEANUP_SECS),
        daemon=True,
    )
    t.start()

    return destino


# ── Abrir Explorador y cliente de correo ─────────────────────────────────────

def _abrir_explorador_temp(temp: Path) -> None:
    """Abre el Explorador de Windows apuntando a la carpeta temporal."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", str(temp)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(temp)])
    else:
        subprocess.Popen(["xdg-open", str(temp)])


def _abrir_mailto(destinatario: str, asunto: str, cuerpo: str) -> None:
    """Abre el cliente de correo predeterminado vía protocolo mailto:."""
    uri = (
        f"mailto:{quote(destinatario)}"
        f"?subject={quote(asunto)}"
        f"&body={quote(cuerpo)}"
    )
    if sys.platform == "win32":
        os.startfile(uri)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", uri])
    else:
        subprocess.Popen(["xdg-open", uri])


# ── Diálogo principal ─────────────────────────────────────────────────────────
class DialogoEnviarEmail(QDialog):

    def __init__(self, pdf_firmado: Path, carpeta_firmados: Path,
                 config: dict, paginas: list, nombre_doc: str, parent=None):
        super().__init__(parent)
        self.pdf_firmado      = pdf_firmado
        self.carpeta_firmados = carpeta_firmados
        self.paginas          = paginas
        self.nombre_doc       = nombre_doc

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
            f"Se abrirá una carpeta con <b>{self.pdf_firmado.name}</b> listo para adjuntar, "
            f"y tu cliente de correo con el asunto prellenado."
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

        # ─ Resumen del documento
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
            "ℹ️  Se abrirá una carpeta temporal con solo el archivo a enviar "
            "y tu cliente de correo. Arrastrá el PDF al correo y envía. "
            "La carpeta se borra automáticamente en 30 minutos."
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

        self.btn_abrir = QPushButton("✉️  Abrir correo y carpeta")
        self.btn_abrir.setMinimumWidth(200)
        self.btn_abrir.setEnabled(False)
        self.btn_abrir.clicked.connect(self._on_abrir)
        fila_btns.addWidget(self.btn_abrir)
        lay.addLayout(fila_btns)

    # ── Validación ──────────────────────────────────────────────────
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

        try:
            copia_temp = _preparar_temp(self.pdf_firmado, self.carpeta_firmados)
        except Exception as e:
            QMessageBox.critical(
                self, "Error al preparar archivo",
                f"No se pudo crear la carpeta temporal:\n\n{e}"
            )
            self.btn_abrir.setText("✉️  Abrir correo y carpeta")
            self.btn_abrir.setEnabled(True)
            return

        asunto = f"Documento Firmado: {self.nombre_doc}"
        cuerpo = (
            f"Estimado/a,\n\n"
            f"Adjunto encontrará el documento '{self.nombre_doc}' con las páginas firmadas.\n\n"
            f"Este mensaje fue preparado automáticamente por PDF Sign Assistant.\n"
        )

        try:
            # Abrir carpeta temporal (solo el PDF a enviar)
            _abrir_explorador_temp(copia_temp.parent)
            # Abrir cliente de correo con destinatario y asunto
            _abrir_mailto(destinatario, asunto, cuerpo)
        except Exception as e:
            QMessageBox.critical(
                self, "Error al abrir",
                f"No se pudo abrir el correo o la carpeta:\n\n{e}"
            )
            self.btn_abrir.setText("✉️  Abrir correo y carpeta")
            self.btn_abrir.setEnabled(True)
            return

        self.accept()


# ── API pública ───────────────────────────────────────────────────────────────
def enviar_documento(
    pdf_firmado: Path,
    carpeta_firmados: Path,
    config: dict,
    paginas: list,
    nombre_doc: str,
    parent=None,
) -> None:
    DialogoEnviarEmail(
        pdf_firmado=pdf_firmado,
        carpeta_firmados=carpeta_firmados,
        config=config,
        paginas=paginas,
        nombre_doc=nombre_doc,
        parent=parent,
    ).exec()
