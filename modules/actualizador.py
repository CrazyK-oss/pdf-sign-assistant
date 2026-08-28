"""
modules/actualizador.py
============================================================
Capa Qt del actualizador interno: los workers en segundo plano y el
diálogo que ve el usuario.

Toda la lógica (comparar versiones, consultar el servidor, descargar y
VERIFICAR EL HASH, decidir cuándo toca comprobar) vive en
modules/actualizaciones.py, sin Qt, para poder testearla en CI sin
interfaz ni pantalla.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QProgressBar,
    QTextBrowser,
    QVBoxLayout,
)

from modules.actualizaciones import (
    HORAS_ENTRE_CHEQUEOS,
    REPO_DEFECTO,
    InfoActualizacion,
    comparar_versiones,
    consultar_ultima_version,
    descargar_verificado,
    esta_ignorada,
    hay_version_nueva,
    lanzar_instalador,
    marcar_comprobacion,
    parsear_version,
    toca_comprobar,
)
from modules.changelog import notas_de_cambios
from modules.theme import SIZE, SPACE, repolish
from modules.ui import (
    FilaAdaptable,
    abrir_en_sistema,
    boton,
    etiqueta,
    icono_label,
    separador,
)
from modules.version import __version__

log = logging.getLogger(__name__)

# Re-exportados para que el resto de la app siga importando desde acá
__all__ = [
    "HORAS_ENTRE_CHEQUEOS",
    "REPO_DEFECTO",
    "DialogoActualizacion",
    "InfoActualizacion",
    "WorkerComprobar",
    "WorkerDescargar",
    "comparar_versiones",
    "consultar_ultima_version",
    "esta_ignorada",
    "hay_version_nueva",
    "lanzar_instalador",
    "marcar_comprobacion",
    "notas_de_cambios",
    "parsear_version",
    "toca_comprobar",
]


# ─────────────────────────────────────────────────────────────────────────
#  Workers
# ─────────────────────────────────────────────────────────────────────────

class WorkerComprobar(QThread):
    """Consulta la versión disponible sin bloquear la interfaz."""

    resultado = pyqtSignal(object)      # InfoActualizacion | None

    def __init__(self, repo: str = REPO_DEFECTO):
        super().__init__()
        self._repo = repo

    def run(self):
        self.resultado.emit(consultar_ultima_version(self._repo))


class WorkerDescargar(QThread):
    """Envuelve descargar_verificado() para no bloquear la interfaz."""

    progreso = pyqtSignal(int, str)     # (porcentaje, etiqueta)
    listo    = pyqtSignal(str)          # ruta del instalador verificado
    error    = pyqtSignal(str)

    def __init__(self, info: InfoActualizacion):
        super().__init__()
        self._info = info
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True

    def run(self):
        try:
            ruta = descargar_verificado(
                self._info,
                progreso=lambda pct, txt: self.progreso.emit(pct, txt),
                cancelado=lambda: self._cancelado,
            )
            self.listo.emit(ruta)
        except InterruptedError:
            pass                        # cancelación pedida por el usuario
        except Exception as e:                       # noqa: BLE001
            log.error("Error al descargar la actualización: %s", e)
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────────────────
#  Diálogo
# ─────────────────────────────────────────────────────────────────────────

class DialogoActualizacion(QDialog):
    """Avisa de la versión nueva y, si el usuario acepta, la instala."""

    omitir_version = pyqtSignal(str)

    def __init__(self, info: InfoActualizacion, parent=None):
        super().__init__(parent)
        self.info = info
        self._worker: WorkerDescargar | None = None
        self._ruta_instalador: str | None = None

        self.setObjectName("pantalla")
        self.setWindowTitle("Actualización disponible")
        self.setMinimumWidth(440)
        self.resize(560, 520)
        self.setModal(True)
        self._construir_ui()

    def _construir_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"])
        lay.setSpacing(SPACE["sm"])

        fila = QHBoxLayout()
        fila.addWidget(icono_label("chispa", SIZE["icono_lg"],
                                   color="primary"))
        fila.addWidget(etiqueta("Hay una versión nueva", rol="titulo"))
        fila.addStretch()
        lay.addLayout(fila)

        lay.addWidget(etiqueta(
            f"Tenés la <b>{__version__}</b> y está disponible la "
            f"<b>{self.info.version}</b>.", rol="cuerpo", wrap=True))
        lay.addSpacing(SPACE["sm"])
        lay.addWidget(separador())
        lay.addSpacing(SPACE["sm"])

        lay.addWidget(etiqueta("Qué cambió", rol="subtitulo"))
        notas = QTextBrowser()
        notas.setOpenExternalLinks(True)     # los enlaces abren el navegador
        notas.setProperty("readonly", "true")
        repolish(notas)

        # Sólo la parte de cambios: el cuerpo del Release trae después las
        # instrucciones de descarga, que acá no vienen al caso —la app ya
        # está por descargar el instalador sola.
        texto = notas_de_cambios(self.info.notas)
        if not texto:
            texto = (f"El release {self.info.version} no publicó notas.\n\n"
                     f"Podés ver los cambios en {self.info.url_pagina}")
        # Vienen en Markdown; sin renderizar se leían con los '##' y los
        # '-' a la vista.
        try:
            notas.setMarkdown(texto)
        except (AttributeError, TypeError):
            notas.setPlainText(texto)
        lay.addWidget(notas, 1)

        self.barra = QProgressBar()
        self.barra.setRange(0, 100)
        self.barra.setTextVisible(False)
        self.barra.hide()
        lay.addWidget(self.barra)

        self.lbl_estado = etiqueta("", rol="hint", wrap=True)
        self.lbl_estado.hide()
        lay.addWidget(self.lbl_estado)
        lay.addSpacing(SPACE["sm"])

        acciones = FilaAdaptable(breakpoint_px=430, spacing=SPACE["sm"])
        self.btn_omitir = boton("Omitir esta versión", variant="ghost",
                                tooltip="No volver a avisar de la "
                                        f"versión {self.info.version}",
                                on_click=self._omitir)
        acciones.agregar(self.btn_omitir)
        acciones.agregar_stretch()

        self.btn_luego = boton("Ahora no", variant="secondary",
                               on_click=self.reject)
        acciones.agregar(self.btn_luego)

        if self.info.instalable:
            tam = (f"  ({self.info.tamano / 1e6:.0f} MB)"
                   if self.info.tamano else "")
            self.btn_principal = boton(f"Actualizar ahora{tam}",
                                       height=SIZE["btn_lg"], min_w=190,
                                       on_click=self._actualizar)
        else:
            # Modo portable o Release sin instalador: sólo llevamos a la
            # página de descargas, no hay nada que instalar solo.
            self.btn_principal = boton("Ver la descarga", height=SIZE["btn_lg"],
                                       min_w=170, on_click=self._abrir_pagina)
            lay.insertWidget(lay.count() - 1, etiqueta(
                "Estás usando la versión portable: descargala y reemplazá "
                "la carpeta manualmente.", rol="hint", wrap=True))
        acciones.agregar(self.btn_principal)
        lay.addWidget(acciones)

        # Sin esto el foco arranca en el panel de notas —es lo primero
        # enfocable— y el diálogo abre con un recuadro resaltado alrededor
        # de un texto que no se edita. Además, así Enter actualiza.
        self.btn_principal.setDefault(True)
        self.btn_principal.setFocus()

    # ── Acciones ──────────────────────────────────────────────────────
    def _abrir_pagina(self):
        abrir_en_sistema(self.info.url_pagina)
        self.accept()

    def _omitir(self):
        self.omitir_version.emit(self.info.version)
        self.reject()

    def _actualizar(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self.btn_principal.setEnabled(False)
        self.btn_omitir.setEnabled(False)
        self.btn_luego.setText("Cancelar")
        self.barra.setValue(0)
        self.barra.show()
        self.lbl_estado.setText("Conectando…")
        self.lbl_estado.setProperty("rol", "ok")
        repolish(self.lbl_estado)
        self.lbl_estado.show()

        self._worker = WorkerDescargar(self.info)
        self._worker.progreso.connect(self._on_progreso)
        self._worker.listo.connect(self._on_descargado)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progreso(self, pct: int, texto: str):
        self.barra.setValue(pct)
        self.lbl_estado.setText(texto)

    def _on_descargado(self, ruta: str):
        self._ruta_instalador = ruta
        self.lbl_estado.setText("Descarga verificada. Iniciando la instalación…")

        if not lanzar_instalador(ruta):
            self._on_error("No se pudo iniciar el instalador.")
            return

        QMessageBox.information(
            self, "Actualizando",
            "La aplicación se va a cerrar para completar la actualización.\n"
            "Se abrirá sola cuando termine.")
        self.accept()
        # El instalador (Restart Manager) cierra la app; salimos por las
        # nuestras para no pelearle los archivos.
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    def _on_error(self, mensaje: str):
        self.barra.hide()
        self.lbl_estado.setText(mensaje)
        self.lbl_estado.setProperty("rol", "error")
        repolish(self.lbl_estado)
        self.btn_principal.setEnabled(True)
        self.btn_omitir.setEnabled(True)
        self.btn_luego.setText("Ahora no")

    def reject(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancelar()
            self._worker.wait(3000)
        super().reject()
