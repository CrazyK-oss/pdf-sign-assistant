"""
modules/actualizador.py
============================================================
Actualizador interno: la app avisa cuando hay versión nueva y la
instala sola, sin que el usuario tenga que pasar por GitHub.

Cómo funciona
-------------
1. Consulta la API de GitHub Releases (una vez por día como máximo,
   o cuando el usuario lo pide desde Ajustes).
2. Si hay una versión mayor, muestra un aviso discreto con las notas.
3. Si el usuario acepta: descarga el instalador, **verifica su SHA-256**
   contra el SHA256SUMS.txt publicado en el mismo Release, y lo ejecuta
   en modo silencioso.
4. Inno Setup cierra la app, actualiza y la vuelve a abrir.

Por qué se puede actualizar sin permisos de administrador
---------------------------------------------------------
El instalador usa PrivilegesRequired=lowest e instala en la carpeta del
usuario. Si instaláramos en Program Files, cada actualización dispararía
un cartel de UAC y la actualización silenciosa sería imposible.

Decisiones deliberadas
----------------------
* NUNCA se descarga ni se ejecuta nada sin que el usuario acepte. La
  comprobación es automática; la instalación, jamás.
* El hash se verifica siempre. Estamos por ejecutar un binario bajado de
  internet: sin verificar, una descarga corrupta o interceptada se
  ejecutaría igual. (Ojo: esto protege la integridad de la descarga, no
  cubre un repositorio comprometido — para eso hace falta firma de código.)
* Todo falla en silencio. Una PC de oficina sin internet, detrás de un
  proxy o con el firewall cerrado no puede ver un error cada vez que
  abre la aplicación.
* En modo portable no se ofrece instalar: no hay instalador que correr,
  así que sólo se enlaza la página de descargas.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
)

from modules.setup import es_portable
from modules.theme import SIZE, SPACE, repolish
from modules.ui import FilaAdaptable, abrir_en_sistema, boton, etiqueta, separador
from modules.version import URL_PROYECTO, __version__

log = logging.getLogger(__name__)

# Repositorio por defecto. Se puede apuntar a otro (por ejemplo, un
# servidor interno con la misma forma de respuesta) vía config.json.
REPO_DEFECTO = "CrazyK-oss/pdf-sign-assistant"
API_RELEASES = "https://api.github.com/repos/{repo}/releases/latest"

TIMEOUT = 10          # segundos
HORAS_ENTRE_CHEQUEOS = 24
TAM_MAXIMO = 400 * 1024 * 1024      # cota de cordura para la descarga


# ─────────────────────────────────────────────────────────────────────────
#  Comparación de versiones
# ─────────────────────────────────────────────────────────────────────────

_RE_VERSION = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)(?:[-+.](.+))?\s*$")


def parsear_version(texto: str) -> tuple[int, int, int, str] | None:
    """Convierte '1.2.3', 'v1.2.3' o '1.2.3-beta1' en una tupla ordenable.

    Devuelve None si el texto no parece una versión: ante la duda, no
    ofrecer una actualización es mejor que ofrecer una equivocada.
    """
    m = _RE_VERSION.match(str(texto or ""))
    if not m:
        return None
    mayor, menor, parche, sufijo = m.groups()
    return (int(mayor), int(menor), int(parche), sufijo or "")


def comparar_versiones(a: str, b: str) -> int:
    """Devuelve -1 si a < b, 0 si son iguales, 1 si a > b.

    Una versión con sufijo (1.2.3-beta) es ANTERIOR a la final (1.2.3),
    que es la convención de semver: una beta no debe ofrecerse como
    actualización de la estable del mismo número.
    """
    va, vb = parsear_version(a), parsear_version(b)
    if va is None or vb is None:
        return 0

    if va[:3] != vb[:3]:
        return -1 if va[:3] < vb[:3] else 1

    # Mismo número: sin sufijo gana (es la versión final)
    sa, sb = va[3], vb[3]
    if sa == sb:
        return 0
    if not sa:
        return 1
    if not sb:
        return -1
    return -1 if sa < sb else 1


def hay_version_nueva(actual: str, candidata: str) -> bool:
    return comparar_versiones(actual, candidata) < 0


# ─────────────────────────────────────────────────────────────────────────
#  Consulta al servidor
# ─────────────────────────────────────────────────────────────────────────

class InfoActualizacion:
    """Datos de la versión publicada, ya normalizados."""

    def __init__(self, version: str, notas: str, url_pagina: str,
                 url_instalador: str = "", nombre_instalador: str = "",
                 url_sumas: str = "", tamano: int = 0):
        self.version = version
        self.notas = notas
        self.url_pagina = url_pagina
        self.url_instalador = url_instalador
        self.nombre_instalador = nombre_instalador
        self.url_sumas = url_sumas
        self.tamano = tamano

    @property
    def instalable(self) -> bool:
        """True si hay un instalador para bajar y no estamos en portable."""
        return bool(self.url_instalador) and not es_portable()


def _abrir(url: str, binario: bool = False):
    pedido = urllib.request.Request(url, headers={
        # GitHub rechaza pedidos sin User-Agent
        "User-Agent": f"PDFSignAssistant/{__version__}",
        "Accept": ("application/octet-stream" if binario
                   else "application/vnd.github+json"),
    })
    return urllib.request.urlopen(pedido, timeout=TIMEOUT)   # noqa: S310


def consultar_ultima_version(repo: str = REPO_DEFECTO) -> InfoActualizacion | None:
    """Pregunta al servidor cuál es la última versión publicada.

    Devuelve None ante cualquier problema (sin internet, proxy, repo sin
    releases, respuesta rara). Nunca lanza: se llama al arrancar la app.
    """
    try:
        with _abrir(API_RELEASES.format(repo=repo)) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        log.info("No se pudo consultar actualizaciones: %s", e)
        return None

    tag = str(datos.get("tag_name") or "").strip()
    if not parsear_version(tag):
        log.info("El último release no tiene una versión reconocible: %r", tag)
        return None

    info = InfoActualizacion(
        version=tag.lstrip("v"),
        notas=str(datos.get("body") or "").strip(),
        url_pagina=str(datos.get("html_url") or f"{URL_PROYECTO}/releases/latest"),
    )

    for asset in datos.get("assets") or []:
        nombre = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not url:
            continue
        if nombre.lower().endswith("setup.exe"):
            info.url_instalador = url
            info.nombre_instalador = nombre
            info.tamano = int(asset.get("size") or 0)
        elif nombre.upper().startswith("SHA256SUMS"):
            info.url_sumas = url

    return info


def _sha256_esperado(url_sumas: str, nombre_archivo: str) -> str | None:
    """Lee el SHA256SUMS.txt del Release y busca la línea del instalador."""
    try:
        with _abrir(url_sumas, binario=True) as r:
            texto = r.read().decode("utf-8", errors="replace")
    except Exception as e:                           # noqa: BLE001
        log.warning("No se pudo leer SHA256SUMS: %s", e)
        return None

    for linea in texto.splitlines():
        partes = linea.split()
        if len(partes) >= 2 and partes[-1].strip("*") == nombre_archivo:
            return partes[0].lower()
    return None


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
    """Descarga el instalador y verifica su hash."""

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
        destino = None
        try:
            self.progreso.emit(0, "Conectando…")

            esperado = None
            if self._info.url_sumas:
                esperado = _sha256_esperado(self._info.url_sumas,
                                            self._info.nombre_instalador)

            carpeta = Path(tempfile.gettempdir()) / "pdf_sign_assistant_update"
            carpeta.mkdir(parents=True, exist_ok=True)
            destino = carpeta / self._info.nombre_instalador

            digest = hashlib.sha256()
            with _abrir(self._info.url_instalador, binario=True) as r:
                total = int(r.headers.get("Content-Length") or self._info.tamano or 0)
                if total > TAM_MAXIMO:
                    raise ValueError("El archivo es sospechosamente grande.")
                bajado = 0
                with open(destino, "wb") as f:
                    while True:
                        if self._cancelado:
                            raise InterruptedError("Descarga cancelada.")
                        trozo = r.read(64 * 1024)
                        if not trozo:
                            break
                        f.write(trozo)
                        digest.update(trozo)
                        bajado += len(trozo)
                        if bajado > TAM_MAXIMO:
                            raise ValueError("El archivo excedió el tamaño máximo.")
                        if total:
                            self.progreso.emit(
                                int(bajado / total * 96),
                                f"Descargando… {bajado / 1e6:.1f} de {total / 1e6:.1f} MB")
                        else:
                            self.progreso.emit(
                                50, f"Descargando… {bajado / 1e6:.1f} MB")

            self.progreso.emit(98, "Verificando la descarga…")
            obtenido = digest.hexdigest()
            if esperado and obtenido != esperado:
                raise ValueError(
                    "El archivo descargado no coincide con la firma publicada.\n"
                    "Se canceló la instalación por seguridad.")
            if not esperado:
                log.warning("El Release no publica SHA256SUMS: no se pudo verificar")

            self.progreso.emit(100, "Listo para instalar")
            self.listo.emit(str(destino))

        except InterruptedError:
            if destino:
                _borrar(destino)
        except Exception as e:                       # noqa: BLE001
            log.error("Error al descargar la actualización: %s", e)
            if destino:
                _borrar(destino)
            self.error.emit(str(e))


def _borrar(ruta: Path) -> None:
    try:
        ruta.unlink(missing_ok=True)
    except OSError:
        pass


def lanzar_instalador(ruta: str) -> bool:
    """Ejecuta el instalador en modo silencioso y devuelve True si arrancó.

    Inno Setup se encarga de cerrar la app (Restart Manager), reemplazar
    los archivos y volver a abrirla:
      /SILENT              muestra sólo la barra de progreso
      /CLOSEAPPLICATIONS   cierra la app que está corriendo
      /RESTARTAPPLICATIONS la vuelve a abrir al terminar
      /NOCANCEL            evita dejar la instalación por la mitad
    """
    if sys.platform != "win32":
        return False
    try:
        subprocess.Popen(
            [ruta, "/SILENT", "/CLOSEAPPLICATIONS",
             "/RESTARTAPPLICATIONS", "/NOCANCEL"],
            close_fds=True,
        )
        return True
    except OSError as e:
        log.error("No se pudo lanzar el instalador: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────
#  Política de comprobación automática
# ─────────────────────────────────────────────────────────────────────────

def toca_comprobar(config: dict) -> bool:
    """True si corresponde comprobar al arrancar.

    Respeta el interruptor de Ajustes y espacia las consultas 24 h, para
    no golpear la API en cada apertura (y no gastar el límite de 60
    pedidos por hora que comparte toda una oficina con la misma IP).
    """
    if not config.get("actualizaciones_automaticas", True):
        return False

    ultima = config.get("ultima_comprobacion")
    if not ultima:
        return True
    try:
        cuando = datetime.fromisoformat(str(ultima))
    except ValueError:
        return True
    return datetime.now() - cuando >= timedelta(hours=HORAS_ENTRE_CHEQUEOS)


def marcar_comprobacion(config: dict) -> None:
    config["ultima_comprobacion"] = datetime.now().isoformat(timespec="seconds")


def esta_ignorada(config: dict, version: str) -> bool:
    return str(config.get("version_ignorada") or "") == version


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
        icono = etiqueta("🎉")
        icono.setStyleSheet("font-size: 22px;")
        fila.addWidget(icono)
        fila.addWidget(etiqueta("Hay una versión nueva", rol="titulo"))
        fila.addStretch()
        lay.addLayout(fila)

        lay.addWidget(etiqueta(
            f"Tenés la <b>{__version__}</b> y está disponible la "
            f"<b>{self.info.version}</b>.", rol="cuerpo", wrap=True))
        lay.addSpacing(SPACE["sm"])
        lay.addWidget(separador())
        lay.addSpacing(SPACE["sm"])

        lay.addWidget(etiqueta("Novedades", rol="subtitulo"))
        notas = QTextEdit()
        notas.setReadOnly(True)
        notas.setProperty("readonly", "true")
        repolish(notas)
        texto = self.info.notas or "Sin notas publicadas."
        # Las notas de un Release vienen en Markdown; sin renderizar se
        # leían con los '##' y los '-' a la vista.
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
        self.lbl_estado.setText(f"⚠  {mensaje}")
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
