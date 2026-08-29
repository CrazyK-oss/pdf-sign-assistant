"""
modules/hojas.py
============================================================
Los dos problemas que aparecen al escanear tacos de hojas.

Uno: los dorsos en blanco
-------------------------
Escanear en dúplex un taco donde algunas hojas están impresas de un solo
lado devuelve el dorso igual: una página en blanco por cada hoja simple.
Un legajo de 30 hojas con 10 impresas de un lado sale con 10 páginas
vacías repartidas por el medio. Nadie las quiere, y sacarlas a mano de a
una es peor que el problema.

Detectarlas no es "buscar píxeles blancos". El papel escaneado no es
blanco puro: tiene el gris del propio papel, ruido del sensor, la sombra
del rodillo en los bordes y, si el original tiene algo impreso del otro
lado, hasta un fantasma de la tinta que se transparenta. Por eso acá se
mide la COBERTURA DE TINTA sobre el área útil, recortando los bordes, y
se compara con un umbral generoso.

La política es conservadora a propósito: ante la duda, la hoja NO está en
blanco. Dejar una página vacía de más es una molestia; borrar una página
con contenido es perder trabajo del usuario.

Dos: escanear las dos caras sin dúplex
--------------------------------------
Un alimentador sin dúplex obliga al truco de siempre: pasar todo el taco
(los frentes), darlo vuelta, pasarlo de nuevo (los dorsos) e intercalar.
Lo que casi nadie acierta a mano es que, al dar vuelta el taco, los
dorsos salen AL REVÉS. Intercalarlos en el orden en que llegaron deja el
documento con las caras cruzadas, y el error se descubre leyéndolo.

Este módulo es Python puro salvo la lectura de imágenes, que usa Pillow
detrás de un import protegido: sin ella, `es_hoja_en_blanco` contesta
"no sé" (False) y no se rompe nada.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

#: Por debajo de este gris (0 = negro, 255 = blanco) un píxel cuenta como
#: tinta. Deliberadamente bajo: el papel escaneado ronda 235-250 y el ruido
#: del sensor lo baja unos puntos, así que un umbral alto contaría el ruido
#: como contenido y no detectaría nunca una hoja vacía.
UMBRAL_TINTA = 200

#: Fracción de cada borde que se descarta antes de medir. El alimentador
#: deja una franja oscura arriba y abajo —sombra del rodillo, y el borde
#: de la hoja contra el fondo del escáner—, y esas franjas por sí solas
#: bastan para que una hoja vacía parezca tener contenido.
#:
#: Es chico a propósito. Recortar más limpiaría mejor, pero el margen
#: inferior es justo donde vive el número de folio: con un 5 % se dejaba
#: de ver, y una hoja cuyo único contenido era su número de página se
#: daba por vacía.
MARGEN_BORDE = 0.02

#: Cobertura por debajo de la cual la hoja se considera vacía.
#:
#: El número sale de medir, no de elegirlo lindo. Al reducir la imagen a
#: LADO_ANALISIS el ruido del sensor se promedia y desaparece: una hoja
#: realmente vacía mide 0,0000 %, incluso simulando un sensor muy sucio.
#: La marca real más chica que se probó —un número de folio al pie— mide
#: 0,05 %, y tres perforaciones de carpeta 0,18 %.
#:
#: Así que el umbral no está "en el medio" de nada: está apenas por encima
#: de cero, para que CUALQUIER marca real sobreviva. Una hoja con una
#: mancha, un sello o un folio no se marca como vacía; sólo la que no
#: tiene absolutamente nada.
COBERTURA_VACIA = 0.0002

#: Lado al que se reduce la imagen para medir. No hace falta más: se está
#: contando qué proporción de la hoja tiene tinta, no leyéndola.
LADO_ANALISIS = 400


def _pillow():
    try:
        from PIL import Image
        return Image
    except ImportError:                                  # pragma: no cover
        log.info("Pillow no está: no se pueden detectar las hojas en blanco")
        return None


def cobertura_de_tinta(ruta: str | Path, *, umbral: int = UMBRAL_TINTA,
                       margen: float = MARGEN_BORDE) -> float:
    """Qué fracción del área útil de la hoja tiene tinta, entre 0 y 1.

    Devuelve -1.0 si la imagen no se pudo leer, que NO es lo mismo que 0:
    una hoja ilegible no es una hoja vacía, y confundirlas haría que un
    archivo dañado se borre solo.
    """
    Image = _pillow()
    if Image is None:
        return -1.0

    try:
        with Image.open(str(ruta)) as img:
            gris = img.convert("L")
            gris.thumbnail((LADO_ANALISIS, LADO_ANALISIS))

            ancho, alto = gris.size
            dx, dy = int(ancho * margen), int(alto * margen)
            if ancho - 2 * dx > 0 and alto - 2 * dy > 0:
                gris = gris.crop((dx, dy, ancho - dx, alto - dy))

            total = gris.width * gris.height
            if total <= 0:
                return -1.0
            # El histograma da la cuenta por nivel de gris de una pasada,
            # sin recorrer píxel por píxel desde Python.
            histograma = gris.histogram()
            oscuros = sum(histograma[:max(0, min(256, umbral))])
            return oscuros / total
    except Exception as e:                               # noqa: BLE001
        log.debug("No se pudo analizar %s: %s", ruta, e)
        return -1.0


def es_hoja_en_blanco(ruta: str | Path, *, cobertura: float = COBERTURA_VACIA,
                      umbral: int = UMBRAL_TINTA) -> bool:
    """True si la hoja parece vacía.

    Ante la duda contesta False. Dejar una página en blanco de más es una
    molestia; borrar una con contenido es perder trabajo del usuario, y de
    eso no se vuelve.
    """
    medida = cobertura_de_tinta(ruta, umbral=umbral)
    if medida < 0:
        return False                                     # ilegible ≠ vacía
    return medida < cobertura


def hojas_en_blanco(rutas, *, cobertura: float = COBERTURA_VACIA) -> list[int]:
    """Posiciones (0-based) de las hojas que parecen vacías."""
    return [i for i, r in enumerate(rutas)
            if es_hoja_en_blanco(r, cobertura=cobertura)]


def paginas_en_blanco(paginas, *, cobertura: float = COBERTURA_VACIA) -> list:
    """Las páginas de un documento que parecen vacías.

    Sólo mira las que son imágenes: una página que viene de un PDF puede
    estar en blanco a propósito —una portada, un separador— y además
    rasterizarla para averiguarlo costaría más de lo que vale.
    """
    return [p for p in paginas
            if getattr(p, "es_imagen", False)
            and es_hoja_en_blanco(p.ruta, cobertura=cobertura)]


# ═══════════════════════════════════════════════════════════════════════════════
#  Dos pasadas: frentes y dorsos
# ═══════════════════════════════════════════════════════════════════════════════

def intercalar(frentes, dorsos, *, dorsos_al_reves: bool = True) -> list:
    """Une los frentes con sus dorsos en el orden final del documento.

    Es el flujo para alimentadores SIN dúplex: se pasa el taco entero, se
    lo da vuelta y se lo pasa de nuevo.

    `dorsos_al_reves` viene en True porque es lo que pasa de verdad: al
    sacar el taco de la bandeja de salida y darlo vuelta, la última hoja
    queda arriba, así que los dorsos entran en orden inverso. Intercalarlos
    tal como llegaron deja cada frente con el dorso de otra hoja, y eso se
    descubre recién leyendo el documento terminado.

    Si las cantidades no coinciden —una hoja que entró doble, o el usuario
    que cortó la segunda pasada— no se inventa nada: se intercala hasta
    donde alcanza y lo que sobra va al final, en orden.
    """
    frentes = list(frentes)
    dorsos = list(reversed(list(dorsos))) if dorsos_al_reves else list(dorsos)

    salida: list = []
    for i in range(max(len(frentes), len(dorsos))):
        if i < len(frentes):
            salida.append(frentes[i])
        if i < len(dorsos):
            salida.append(dorsos[i])
    return salida


def descuadre(frentes, dorsos) -> int:
    """Cuántas hojas de diferencia hay entre las dos pasadas.

    Distinto de cero casi siempre significa que el alimentador tomó dos
    hojas juntas. Conviene avisarlo antes de intercalar: el documento
    resultante va a estar mal y no de forma evidente.
    """
    return abs(len(list(frentes)) - len(list(dorsos)))
