"""
modules/previa.py
============================================================
Dibuja una página —venga de donde venga— al tamaño en que se la va a ver.

Esto vivía dentro de "Escanear a PDF" y sólo sabía de imágenes. Ahora una
página puede ser una página de un PDF, y las dos herramientas necesitan lo
mismo: una miniatura chica para la lista y una vista previa grande para el
panel. De ahí que salga a un módulo propio.

Las dos reglas que hacen que esto no sea trivial
------------------------------------------------
1. **Nunca se decodifica más de lo que se va a mostrar.** Un escaneo A4 a
   300 DPI son ~8,7 millones de píxeles: cargarlo entero para mostrarlo de
   92 px de alto son unos 35 MB de RAM por página. Para imágenes eso lo
   resuelve `QImageReader.setScaledSize()`, que le pide al decodificador la
   imagen ya chica; para PDF, el factor de zoom que se le pasa a PyMuPDF,
   que rasteriza directo al tamaño pedido.

2. **Tampoco se decodifica de menos.** "Chica" no es un número fijo: la
   miniatura y la previa piden cada una el tamaño que ocupan de verdad —el
   panel de la previa crece con la ventana— multiplicado por el
   devicePixelRatio de la pantalla. Con un tope fijo, la previa terminaba
   AGRANDANDO la imagen y se veía blanda.

Sobre los archivos abiertos
---------------------------
El PDF se abre y se cierra en cada render, sin mantener documentos vivos
en un cache. Tener el archivo abierto sería más rápido, pero en Windows
impide renombrar encima de él, y guardar el resultado sobre el PDF que se
abrió es de lo más común. El cache de pixmaps ya evita repetir el trabajo.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImage, QImageReader, QPixmap, QTransform
from PyQt6.QtWidgets import QLabel

from modules.documento import ORIGEN_PDF

log = logging.getLogger(__name__)

#: Alto de la miniatura de la lista, en píxeles lógicos.
LADO_MINIATURA = 92

#: Tope de la vista previa. NO es el tamaño al que se lee: la previa se lee
#: al tamaño que realmente ocupa el panel (que crece con la ventana) por el
#: devicePixelRatio de la pantalla. Este número sólo evita que en un monitor
#: enorme se rasterice la página casi entera.
LADO_PREVIA_MAX = 1800

#: Los pedidos de tamaño se redondean hacia arriba a un múltiplo de esto.
#: Sin cuantizar, arrastrar el borde de la ventana pediría un tamaño
#: distinto por cada píxel y el cache no serviría de nada.
PASO_TAMANO = 128

#: Tope del cache, en bytes. Se acota por BYTES y no por cantidad de
#: entradas: la vista previa puede pedir pixmaps de varios MB, y un tope de
#: "160 entradas" que estaba bien para miniaturas de 0,5 MB pasaría a
#: permitir más de un gigabyte sin que nadie lo note.
CACHE_BYTES_MAX = 96 * 1024 * 1024

#: (ruta, mtime, indice, lado, rotación) → QPixmap
_CACHE: OrderedDict[tuple, QPixmap] = OrderedDict()
_cache_bytes = 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Cache
# ═══════════════════════════════════════════════════════════════════════════════

def _peso(pm: QPixmap) -> int:
    """Bytes que ocupa un pixmap en memoria (4 por píxel)."""
    return max(0, pm.width() * pm.height() * 4)


def _guardar(clave: tuple, pm: QPixmap) -> QPixmap:
    global _cache_bytes
    _CACHE[clave] = pm
    _cache_bytes += _peso(pm)
    while _CACHE and _cache_bytes > CACHE_BYTES_MAX:
        _, viejo = _CACHE.popitem(last=False)
        _cache_bytes -= _peso(viejo)
    return pm


def limpiar_cache() -> None:
    """Vacía el cache (lo usan los tests y el cierre de cada vista)."""
    global _cache_bytes
    _CACHE.clear()
    _cache_bytes = 0


def bytes_en_cache() -> int:
    """Cuánta memoria está ocupando el cache. Para tests y diagnóstico."""
    return _cache_bytes


def cuantizar(lado: int, paso: int = PASO_TAMANO) -> int:
    """Redondea hacia arriba al múltiplo de `paso` (mínimo, un paso)."""
    lado = max(1, int(lado))
    return max(paso, -(-lado // paso) * paso)


# ═══════════════════════════════════════════════════════════════════════════════
#  Render por origen
# ═══════════════════════════════════════════════════════════════════════════════

def _leer_imagen(ruta: str, lado_max: int) -> QPixmap:
    """Una imagen del disco, decodificada ya reducida."""
    lector = QImageReader(ruta)
    lector.setAutoTransform(True)          # respeta la orientación EXIF
    tam = lector.size()
    if tam.isValid() and tam.width() > 0 and tam.height() > 0:
        escala = min(lado_max / tam.width(), lado_max / tam.height(), 1.0)
        if escala < 1.0:
            lector.setScaledSize(QSize(max(1, round(tam.width() * escala)),
                                       max(1, round(tam.height() * escala))))
    imagen = lector.read()
    if imagen.isNull():
        log.debug("No se pudo leer la imagen %s: %s", ruta, lector.errorString())
        return QPixmap()
    return QPixmap.fromImage(imagen)


def _leer_pagina_pdf(ruta: str, indice: int, lado_max: int) -> QPixmap:
    """Una página de un PDF, rasterizada al tamaño pedido.

    El zoom se calcula para que el lado mayor quede en `lado_max`. `rect`
    ya viene con la rotación propia de la página aplicada, así que un
    documento guardado apaisado se ve apaisado sin hacer nada.

    A diferencia de las imágenes, acá sí se agranda si hace falta: una
    página de PDF es vectorial y ampliarla no pierde nitidez, es
    justamente lo que uno quiere al mirar la previa de un texto chico.
    """
    try:
        import pymupdf
    except ImportError:                                  # pragma: no cover
        log.warning("PyMuPDF no está: no se puede previsualizar el PDF %s", ruta)
        return QPixmap()

    doc = None
    try:
        doc = pymupdf.open(ruta)
        if not 0 <= indice < doc.page_count:
            return QPixmap()
        pagina = doc[indice]
        caja = pagina.rect
        lado = max(caja.width, caja.height)
        zoom = (lado_max / lado) if lado > 0 else 1.0
        pix = pagina.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        # `samples` es RGB de 8 bits sin relleno; `stride` evita el clásico
        # de la imagen "rayada" en diagonal cuando la fila lleva padding.
        imagen = QImage(pix.samples, pix.width, pix.height, pix.stride,
                        QImage.Format.Format_RGB888)
        # copy() porque QImage no se queda con los bytes: al cerrar el
        # documento, `samples` deja de ser válido y el pixmap saldría negro.
        return QPixmap.fromImage(imagen.copy())
    except Exception as e:                               # noqa: BLE001
        log.debug("No se pudo dibujar la página %d de %s: %s", indice, ruta, e)
        return QPixmap()
    finally:
        if doc is not None:
            doc.close()


def render(pagina, lado_max: int) -> QPixmap:
    """Dibuja una página al tamaño pedido, con su rotación aplicada.

    `pagina` es cualquier cosa con ruta/rotacion/origen/indice: sirve tanto
    un `Pagina` del modelo como un `PaginaPlana` del motor de armado.

    El mtime entra en la clave del cache para que reescanear sobre el mismo
    temporal —o que el usuario edite el PDF por fuera— no devuelva la
    imagen vieja.
    """
    ruta = str(pagina.ruta)
    indice = int(getattr(pagina, "indice", 0))
    rotacion = int(getattr(pagina, "rotacion", 0)) % 360
    es_pdf = getattr(pagina, "origen", "") == ORIGEN_PDF

    try:
        mtime = Path(ruta).stat().st_mtime
    except OSError:
        return QPixmap()

    clave = (ruta, mtime, indice, lado_max, rotacion)
    cacheado = _CACHE.get(clave)
    if cacheado is not None:
        _CACHE.move_to_end(clave)
        return cacheado

    pm = (_leer_pagina_pdf(ruta, indice, lado_max) if es_pdf
          else _leer_imagen(ruta, lado_max))
    if pm.isNull():
        return pm                       # los fallos no se cachean: pueden
                                        # ser transitorios (archivo a medio
                                        # escribir por el escáner)
    if rotacion:
        pm = pm.transformed(QTransform().rotate(rotacion),
                            Qt.TransformationMode.SmoothTransformation)
    return _guardar(clave, pm)


def miniatura(pagina, lado: int = LADO_MINIATURA, *, dpr: float = 1.0) -> QPixmap:
    """La versión chica, para la lista de páginas."""
    pm = render(pagina, cuantizar(max(1, int(round(lado * max(1.0, dpr))))))
    if pm.isNull():
        return pm
    escalado = pm.scaled(QSize(lado, lado), Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    escalado.setDevicePixelRatio(1.0)
    return escalado


def escalar_para(etiqueta: QLabel, pagina, *,
                 tope: int = LADO_PREVIA_MAX) -> QPixmap:
    """Devuelve la página lista para poner en `etiqueta`.

    El error que esto corrige: leer siempre a un tope fijo y después
    escalar al widget. Si el widget era más grande que ese tope —y el panel
    de la vista previa crece con la ventana— el resultado se **agrandaba**
    a partir de menos píxeles de los disponibles, y se veía blando. Medido
    antes del arreglo: 1,14× en una ventana de 1000 px y 2,63× en una de
    2560.

    Acá se pide la página al tamaño que el widget ocupa DE VERDAD, contando
    el devicePixelRatio, de modo que en un monitor con escalado al 150 % se
    lean los píxeles que hacen falta y no la mitad.
    """
    dpr = max(1.0, float(etiqueta.devicePixelRatioF()))
    ancho = max(1, int(round(etiqueta.width() * dpr)))
    alto = max(1, int(round(etiqueta.height() * dpr)))

    lado = min(cuantizar(max(ancho, alto)), tope)
    pm = render(pagina, lado)
    if pm.isNull():
        return pm

    escalado = pm.scaled(QSize(ancho, alto),
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    # Sin esto, en pantallas HiDPI Qt dibujaría el pixmap al doble de
    # tamaño en vez de usarlo para ganar nitidez.
    escalado.setDevicePixelRatio(dpr)
    return escalado


def dimensiones(pagina) -> tuple[int, int]:
    """Ancho y alto de la página, sin rasterizarla entera.

    Para una imagen son sus píxeles; para una página de PDF, su tamaño en
    puntos redondeado. No es la misma unidad, pero se usa para el texto
    informativo de la fila, no para calcular nada.
    """
    ruta = str(pagina.ruta)
    if getattr(pagina, "origen", "") == ORIGEN_PDF:
        try:
            import pymupdf
            doc = pymupdf.open(ruta)
            try:
                indice = int(getattr(pagina, "indice", 0))
                if not 0 <= indice < doc.page_count:
                    return (0, 0)
                caja = doc[indice].rect
                return (round(caja.width), round(caja.height))
            finally:
                doc.close()
        except Exception:                                # noqa: BLE001
            return (0, 0)

    tam = QImageReader(ruta).size()
    return (tam.width(), tam.height()) if tam.isValid() else (0, 0)
