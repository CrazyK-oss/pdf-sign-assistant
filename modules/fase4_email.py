"""
modules/fase4_email.py
============================================================
Enviar el PDF firmado por correo.

Estrategia:
  1. El usuario escribe el destinatario y confirma.
  2. Se crea una carpeta temporal _envio_temp/ dentro de pdfs_firmados/
     con únicamente una copia del PDF a enviar.
  3. Se abre esa carpeta en el explorador (con ese único archivo a la
     vista) y, en paralelo, el cliente de correo predeterminado con
     destinatario, asunto y cuerpo prellenados vía mailto:.
  4. El usuario arrastra el archivo al correo y envía.
  5. _envio_temp/ se borra al cerrar la app (closeEvent en main.py) y
     también al arrancar, por si la sesión anterior terminó de golpe.

No requiere pywin32, Outlook ni ningún cliente específico.

Cambios de esta versión
-----------------------
* Se eliminó la paleta y el stylesheet propios del módulo (duplicaban
  el tema con otros colores, así que el diálogo salía en claro aunque
  la app estuviera en oscuro).
* Layout responsive y con menor ancho mínimo.
* El botón de acción también se habilita con Enter, y el diálogo
  recuerda el último destinatario dentro de la sesión.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from urllib.parse import quote

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

from modules.theme import SIZE, SPACE, repolish
from modules.trabajo import formatear_paginas
from modules.ui import (
    FilaAdaptable,
    abrir_en_sistema,
    boton,
    etiqueta,
    separador,
)

TEMP_FOLDER_NAME = "_envio_temp"
EMAIL_REGEX = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]{2,}$")

# Último destinatario usado en esta sesión (evita re-tipear en envíos seguidos)
_ULTIMO_DESTINATARIO = ""


def _es_email_valido(email: str) -> bool:
    return bool(EMAIL_REGEX.match(email.strip()))


def _construir_resumen(nombre_doc: str, paginas: list) -> str:
    """Resumen del documento para el cuerpo del correo.

    Las páginas se muestran comprimidas ("1-4, 7" en vez de
    "1, 2, 3, 4, 7"), que es como se leen en una lista larga.
    """
    if not paginas:
        return (
            f"Documento:              {nombre_doc}\n"
            "Páginas reemplazadas:   (no registradas)"
        )
    plural = "s" if len(paginas) != 1 else ""
    return (
        f"Documento:              {nombre_doc}\n"
        f"Página{plural} reemplazada{plural}:   {formatear_paginas(paginas)}\n"
        f"Total páginas firmadas: {len(paginas)}"
    )


# ── Gestión de la carpeta temporal ────────────────────────────────────────────

def _carpeta_temp(carpeta_firmados: Path) -> Path:
    return carpeta_firmados / TEMP_FOLDER_NAME


def _borrar_temp(carpeta_firmados: Path) -> None:
    """Borra _envio_temp/ si existe. Silencia cualquier error."""
    temp = _carpeta_temp(carpeta_firmados)
    if temp.exists():
        try:
            shutil.rmtree(temp)
        except OSError:
            pass


def limpiar_temp_al_iniciar(carpeta_firmados: Path) -> None:
    """Llamar al arrancar la app: limpia restos de sesiones anteriores."""
    _borrar_temp(carpeta_firmados)


def limpiar_temp_al_salir(carpeta_firmados: Path) -> None:
    """Llamar al cerrar la app (closeEvent / aboutToQuit)."""
    _borrar_temp(carpeta_firmados)


def _preparar_temp(pdf_origen: Path, carpeta_firmados: Path) -> Path:
    """Crea _envio_temp/ con sólo la copia del PDF y devuelve esa ruta."""
    temp = _carpeta_temp(carpeta_firmados)
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True, exist_ok=True)

    destino = temp / pdf_origen.name
    shutil.copy2(pdf_origen, destino)
    return destino


def _abrir_mailto(destinatario: str, asunto: str, cuerpo: str) -> None:
    """Abre el cliente de correo predeterminado vía mailto:."""
    abrir_en_sistema(
        f"mailto:{quote(destinatario)}"
        f"?subject={quote(asunto)}"
        f"&body={quote(cuerpo)}"
    )


# ── Diálogo principal ─────────────────────────────────────────────────────────
class DialogoEnviarEmail(QDialog):

    def __init__(self, pdf_firmado: Path, carpeta_firmados: Path,
                 config: dict, paginas: list, nombre_doc: str, parent=None):
        super().__init__(parent)
        self.pdf_firmado = pdf_firmado
        self.carpeta_firmados = carpeta_firmados
        self.paginas = paginas
        self.nombre_doc = nombre_doc

        self.setWindowTitle("Enviar documento firmado")
        self.setObjectName("pantalla")
        self.setMinimumWidth(420)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"])
        lay.setSpacing(SPACE["sm"])

        # Título
        fila_titulo = QHBoxLayout()
        fila_titulo.setSpacing(SPACE["sm"])
        icono = etiqueta("✉️")
        icono.setStyleSheet("font-size: 20px;")
        fila_titulo.addWidget(icono)
        fila_titulo.addWidget(etiqueta("Enviar por correo", rol="titulo"))
        fila_titulo.addStretch()
        lay.addLayout(fila_titulo)

        lay.addWidget(etiqueta(
            f"Se abrirá una carpeta con «{self.pdf_firmado.name}» listo para "
            "adjuntar, y tu cliente de correo con el asunto prellenado.",
            rol="hint", wrap=True))
        lay.addSpacing(SPACE["sm"])
        lay.addWidget(separador())
        lay.addSpacing(SPACE["sm"])

        # Destinatario
        lay.addWidget(etiqueta("Correo destinatario", rol="subtitulo"))
        self.input_email = QLineEdit()
        self.input_email.setMinimumHeight(SIZE["input"])
        self.input_email.setPlaceholderText("ejemplo@dominio.com")
        self.input_email.setText(_ULTIMO_DESTINATARIO)
        self.input_email.setClearButtonEnabled(True)
        self.input_email.textChanged.connect(self._on_email_changed)
        self.input_email.returnPressed.connect(self._on_abrir)
        lay.addWidget(self.input_email)

        self.lbl_error = etiqueta("", rol="error", wrap=True)
        lay.addWidget(self.lbl_error)
        lay.addSpacing(SPACE["sm"])

        # Resumen
        lay.addWidget(etiqueta("Resumen del documento", rol="subtitulo"))
        self.txt_resumen = QTextEdit()
        self.txt_resumen.setReadOnly(True)
        self.txt_resumen.setProperty("readonly", "true")
        repolish(self.txt_resumen)
        self.txt_resumen.setFixedHeight(80)
        self.txt_resumen.setPlainText(
            _construir_resumen(self.nombre_doc, self.paginas))
        lay.addWidget(self.txt_resumen)
        lay.addSpacing(SPACE["md"])
        lay.addWidget(separador())
        lay.addSpacing(SPACE["sm"])

        lay.addWidget(etiqueta(
            "ℹ️  Arrastrá el PDF desde la carpeta al correo y enviá. "
            "La carpeta temporal se borra al cerrar la app.",
            rol="hint", wrap=True))
        lay.addSpacing(SPACE["md"])

        # Acciones (se apilan si el diálogo queda angosto)
        acciones = FilaAdaptable(breakpoint_px=380, spacing=SPACE["sm"])
        acciones.agregar(boton("Cancelar", variant="secondary",
                               on_click=self.reject))
        acciones.agregar_stretch()
        self.btn_abrir = boton("✉️  Abrir correo y carpeta", min_w=200,
                               enabled=False, on_click=self._on_abrir)
        acciones.agregar(self.btn_abrir)
        lay.addWidget(acciones)

        self._on_email_changed(self.input_email.text())

    def _on_email_changed(self, texto: str):
        texto = texto.strip()
        if not texto:
            error, valido = "", False
        elif not _es_email_valido(texto):
            error, valido = "Correo inválido (ejemplo: nombre@dominio.com)", False
        else:
            error, valido = "", True

        self.lbl_error.setText(error)
        self.input_email.setProperty("invalid", "true" if error else "false")
        repolish(self.input_email)
        self.btn_abrir.setEnabled(valido)

    def _on_abrir(self):
        global _ULTIMO_DESTINATARIO
        destinatario = self.input_email.text().strip()
        if not _es_email_valido(destinatario):
            return

        self.btn_abrir.setText("Abriendo…")
        self.btn_abrir.setEnabled(False)

        try:
            copia_temp = _preparar_temp(self.pdf_firmado, self.carpeta_firmados)
        except Exception as e:                       # noqa: BLE001
            QMessageBox.critical(self, "Error al preparar archivo",
                                 f"No se pudo crear la carpeta temporal:\n\n{e}")
            self._restablecer_boton()
            return

        asunto = f"Documento Firmado: {self.nombre_doc}"
        if self.paginas:
            plural = "s" if len(self.paginas) != 1 else ""
            detalle = (f"con la{plural} página{plural} "
                       f"{formatear_paginas(self.paginas)} firmada{plural}")
        else:
            detalle = "con las páginas firmadas"
        cuerpo = (
            "Estimado/a,\n\n"
            f"Adjunto encontrará el documento '{self.nombre_doc}' {detalle}.\n\n"
            "Este mensaje fue preparado automáticamente por PDF Sign Assistant.\n"
        )

        try:
            abrir_en_sistema(copia_temp.parent)
            _abrir_mailto(destinatario, asunto, cuerpo)
        except Exception as e:                       # noqa: BLE001
            QMessageBox.critical(self, "Error al abrir",
                                 f"No se pudo abrir el correo o la carpeta:\n\n{e}")
            self._restablecer_boton()
            return

        _ULTIMO_DESTINATARIO = destinatario
        self.accept()

    def _restablecer_boton(self):
        self.btn_abrir.setText("✉️  Abrir correo y carpeta")
        self.btn_abrir.setEnabled(True)


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
