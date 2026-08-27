"""
modules/escaner_qt.py
============================================================
Puente entre el escáner (modules.dispositivos) y la UI.

Es el hilo que abre el diálogo de digitalización de WIA sin congelar la
ventana. Vive en su propio módulo porque lo usan DOS herramientas —firmar
un PDF y escanear a PDF—, y no correspondía que la segunda importara
código de una fase de la primera.

Puntos delicados que resuelve
-----------------------------
* COM se inicializa EN ESTE HILO. pywin32 no lo hace solo, y sin eso toda
  llamada falla con "CoInitialize has not been called". El usuario veía un
  error genérico del escáner y salía a revisar cables, cuando el problema
  era del código.
* Los com_error se traducen a mensajes con causa y sugerencia.
* Si hay más de un escáner instalado, se le deja elegir cuál.
* Los workers se guardan en un registro global mientras corren: destruir
  un QThread en ejecución revienta el proceso, y la vista que lo lanzó
  puede cerrarse antes de que el diálogo WIA termine.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid

from PyQt6.QtCore import QThread, pyqtSignal

from modules.dispositivos import (
    ErrorDispositivo,
    adquirir_imagen,
    com_inicializado,
    es_cancelacion_usuario,
    interpretar_error_wia,
    listar_escaneres,
)

log = logging.getLogger(__name__)

PREFIJO_TEMP = "pdf_sign_scan_"

#: DPI por defecto de cada herramienta.
#:  - Firmar: 600, porque hay que distinguir el trazo fino de una firma.
#:  - Escanear a PDF: 300, que es calidad de documento y pesa la cuarta
#:    parte; con 20 páginas la diferencia es de cientos de megabytes.
DPI_FIRMA = 600
DPI_DOCUMENTO = 300

# Los workers se registran acá para que sigan vivos aunque la vista se
# cierre: destruir un QThread en ejecución revienta el proceso.
_WORKERS_VIVOS: set[QThread] = set()


class WIAScanWorker(QThread):
    """Abre el diálogo de digitalización de WIA en un hilo aparte."""

    scan_completado = pyqtSignal(str)
    scan_cancelado  = pyqtSignal()
    scan_error      = pyqtSignal(object)    # ErrorDispositivo

    #: Se mantiene como atributo de clase porque el código existente lo
    #: consulta como WIAScanWorker.DPI_SCAN para mostrarlo en pantalla.
    DPI_SCAN = DPI_FIRMA

    def __init__(self, elegir_dispositivo: bool = False, parent=None, *,
                 dpi: int | None = None):
        super().__init__(parent)
        self._elegir_dispositivo = elegir_dispositivo
        self._dpi = int(dpi) if dpi else self.DPI_SCAN

    @property
    def dpi(self) -> int:
        return self._dpi

    def run(self):
        nombre = f"{PREFIJO_TEMP}{uuid.uuid4().hex[:8]}.png"
        ruta_destino = os.path.join(tempfile.gettempdir(), nombre)
        try:
            with com_inicializado() as ok:
                if not ok:
                    raise ErrorDispositivo(
                        "No se pudieron cargar los componentes de Windows "
                        "para escanear.",
                        sugerencia="Instalalos con:  pip install pywin32")

                adquirir_imagen(ruta_destino, dpi=self._dpi,
                                elegir_dispositivo=self._elegir_dispositivo)
                self.scan_completado.emit(ruta_destino)

        except ErrorDispositivo as e:
            self.scan_error.emit(e)
        except Exception as e:                       # noqa: BLE001
            if es_cancelacion_usuario(e):
                self.scan_cancelado.emit()
            else:
                self.scan_error.emit(interpretar_error_wia(e))


def hay_varios_escaneres() -> bool:
    """True si conviene mostrar el selector de dispositivo.

    Con un solo escáner el selector es un clic de más; con dos o más, no
    mostrarlo significa usar siempre el predeterminado de Windows sin
    decir cuál es.
    """
    try:
        return len(listar_escaneres()) > 1
    except Exception:                                # noqa: BLE001
        return False


def lanzar_escaneo(*, elegir_dispositivo: bool | None = None,
                   dpi: int = DPI_DOCUMENTO,
                   al_completar=None, al_cancelar=None,
                   al_fallar=None) -> WIAScanWorker:
    """Crea, registra y arranca un worker de escaneo.

    Centraliza el ritual de mantenerlo vivo y limpiarlo al terminar, que
    es fácil de olvidar y se paga con un cierre abrupto del proceso.
    """
    if elegir_dispositivo is None:
        elegir_dispositivo = hay_varios_escaneres()

    worker = WIAScanWorker(elegir_dispositivo=elegir_dispositivo, dpi=dpi)
    _WORKERS_VIVOS.add(worker)
    worker.finished.connect(lambda: _WORKERS_VIVOS.discard(worker))
    worker.finished.connect(worker.deleteLater)
    if al_completar is not None:
        worker.scan_completado.connect(al_completar)
    if al_cancelar is not None:
        worker.scan_cancelado.connect(al_cancelar)
    if al_fallar is not None:
        worker.scan_error.connect(al_fallar)
    worker.start()
    return worker
