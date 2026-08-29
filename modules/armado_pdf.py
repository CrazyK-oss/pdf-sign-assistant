"""
modules/armado_pdf.py
============================================================
Escribe el PDF final a partir de una lista de páginas.

Antes esto vivía dentro del QThread de "Escanear a PDF" y sólo sabía de
imágenes: cada página se convertía a un PDF de una hoja y después se
pegaban todas. Con "Unir y dividir" aparecieron páginas que ya son PDF, y
con eso una regla que importa mucho más de lo que parece:

    **una página que ya es PDF se copia tal cual, nunca se rasteriza.**

Si se rasterizara, un contrato de 10 páginas con texto seleccionable
volvería convertido en 10 fotos: no se podría buscar ni copiar texto, los
lectores de pantalla no lo leerían, pesaría diez veces más y se vería
peor. Lo único que se rasteriza es lo que ya era una imagen.

De ahí que el armado tenga dos caminos que conviven en el mismo bucle:

    página de PDF  →  se clona en el escritor (pypdf ya la copia sola)
    imagen         →  convertir_imagen_a_pdf() y se agrega esa hoja

El módulo es Python puro a propósito —ni Qt ni hilos—, así que se puede
probar de punta a punta abriendo el PDF resultante, y el QThread de la
pantalla queda como un envoltorio de tres líneas.
"""

from __future__ import annotations

import io
import logging
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from modules.documento import ORIGEN_PDF, Documento
from modules.imagen_pdf import (
    CALIDAD_DEFECTO,
    borrar_si_existe,
    calidad,
    convertir_imagen_a_pdf,
)

log = logging.getLogger(__name__)

#: Metadatos que se le ponen al documento resultante.
PRODUCTOR = "PDF Sign Assistant"


class ErrorArmado(Exception):
    """Algo impidió escribir el PDF, con un mensaje que se le puede mostrar
    al usuario tal cual."""


@dataclass(frozen=True)
class PaginaPlana:
    """Copia inmutable de una página, para pasarle al hilo que escribe.

    El modelo puede cambiar mientras el hilo trabaja —el usuario sigue
    tocando la lista—, así que lo que se arma es la foto del momento en
    que se apretó Guardar y no la lista viva.
    """

    ruta: Path
    rotacion: int = 0
    origen: str = ORIGEN_PDF
    indice: int = 0

    @property
    def es_pdf(self) -> bool:
        return self.origen == ORIGEN_PDF


def instantanea(paginas: Iterable) -> list[PaginaPlana]:
    """Congela las páginas de un documento antes de mandarlas a escribir."""
    return [PaginaPlana(Path(p.ruta), int(p.rotacion), p.origen, int(p.indice))
            for p in paginas]


def _pypdf():
    """pypdf, con PyPDF2 de reserva para instalaciones viejas."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:                                  # pragma: no cover
        from PyPDF2 import PdfReader, PdfWriter  # type: ignore
    return PdfReader, PdfWriter


def _error_dependencia():
    """La excepción que tira pypdf cuando le falta `cryptography`.

    Se busca por nombre y no se importa arriba porque PyPDF2 —el plan B de
    `_pypdf()`— no la tiene. Si no está, se devuelve algo que nunca coincide.
    """
    try:
        from pypdf.errors import DependencyError
        return DependencyError
    except ImportError:                                  # pragma: no cover
        class _Nunca(Exception):
            pass
        return _Nunca


def _protegido(nombre: str) -> ErrorArmado:
    return ErrorArmado(
        f"«{nombre}» está protegido con contraseña.\n"
        "Abrilo en tu lector, guardá una copia sin protección y probá "
        "con esa.")


def _abrir_lector(ruta: Path, datos=None):
    """Abre un PDF y lo deja listo para leer, o explica por qué no se pudo.

    Concentra acá lo que antes estaba repetido en `contar_paginas` y en el
    bucle de armado, porque la parte delicada es la misma: distinguir "no
    es un PDF" de "es un PDF pero está cerrado con llave". Decir lo
    primero cuando pasa lo segundo manda al usuario a buscar un archivo
    dañado que no existe.

    Un PDF cifrado con AES necesita `cryptography` (va en requirements.txt).
    Sin ella pypdf tira DependencyError, que es un caso de "protegido",
    NO de "dañado": eso es lo que rompía el mensaje en el runner de
    Windows, donde la librería no estaba instalada.
    """
    PdfReader, _ = _pypdf()
    fuente = io.BytesIO(datos) if datos is not None else str(ruta)
    try:
        lector = PdfReader(fuente)
    except _error_dependencia():
        raise _protegido(ruta.name) from None
    except Exception as e:                               # noqa: BLE001
        raise ErrorArmado(
            f"No se pudo leer «{ruta.name}»:\n{e}\n\n"
            "Puede estar dañado o no ser un PDF.") from e

    if getattr(lector, "is_encrypted", False):
        # Un PDF "protegido" sin contraseña de apertura —el caso típico:
        # sólo restringe imprimir o copiar— se abre con la clave vacía.
        # Sólo si eso falla hace falta pedirla de verdad.
        try:
            abierto = lector.decrypt("")
        except Exception:                                # noqa: BLE001
            raise _protegido(ruta.name) from None
        if not abierto:
            raise _protegido(ruta.name)

    return lector


# ═══════════════════════════════════════════════════════════════════════════════
#  Lectura de PDF existentes
# ═══════════════════════════════════════════════════════════════════════════════

def contar_paginas(ruta: str | Path) -> int:
    """Cuántas páginas tiene un PDF.

    Lanza ErrorArmado con un mensaje presentable si el archivo no se puede
    abrir: es lo primero que pasa al arrastrar algo que no es un PDF, o uno
    con contraseña, y el usuario merece saber cuál de las dos cosas fue.
    """
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ErrorArmado(f"No se encuentra el archivo:\n{ruta}")
    lector = _abrir_lector(ruta)
    try:
        return len(lector.pages)
    except Exception as e:                               # noqa: BLE001
        raise ErrorArmado(
            f"No se pudo leer «{ruta.name}»:\n{e}\n\n"
            "Puede estar dañado o no ser un PDF.") from e


def abrir_en(documento: Documento, ruta: str | Path, *,
             indice: int | None = None) -> int:
    """Suma al documento todas las páginas de un PDF y devuelve cuántas.

    Es el puente entre el modelo —que a propósito no abre archivos— y
    pypdf. Si es lo primero que se abre, además deja el nombre del archivo
    como base para sugerir al guardar.
    """
    ruta = Path(ruta)
    cantidad = contar_paginas(ruta)
    if cantidad == 0:
        raise ErrorArmado(f"«{ruta.name}» no tiene páginas.")
    if not documento.base_nombre:
        documento.base_nombre = ruta.stem
    documento.agregar_pdf(ruta, cantidad, indice=indice)
    return cantidad


# ═══════════════════════════════════════════════════════════════════════════════
#  Escritura
# ═══════════════════════════════════════════════════════════════════════════════

def armar_pdf(paginas: Sequence, destino: str | Path, *,
              cal=CALIDAD_DEFECTO,
              progreso: Callable[[int, str], None] | None = None,
              cancelado: Callable[[], bool] | None = None) -> Path:
    """Escribe el PDF y devuelve la ruta final.

    `paginas` son `PaginaPlana` (o cualquier cosa con ruta/rotacion/
    origen/indice). `progreso` recibe (porcentaje, texto) y `cancelado` se
    consulta entre páginas para poder abortar sin esperar al final.

    La escritura es en dos pasos —temporal y después `os.replace`— para
    que un corte a mitad de camino no deje truncado el archivo que el
    usuario ya tenía. `os.replace` es atómico dentro del mismo volumen.
    """
    avisar = progreso or (lambda *_: None)
    abortar = cancelado or (lambda: False)
    calidad_ = calidad(cal)
    destino = Path(destino)

    if not paginas:
        raise ErrorArmado("No hay páginas para guardar.")

    PdfReader, PdfWriter = _pypdf()
    escritor = PdfWriter()

    # Un lector por archivo, no por página: abrir el mismo PDF 200 veces
    # para copiar sus 200 páginas lo lee entero 200 veces. Además hay que
    # mantenerlos vivos hasta escribir, porque pypdf resuelve los objetos
    # de las páginas de forma perezosa.
    lectores: dict[str, object] = {}
    temporales: list[str] = []
    parcial: Path | None = None

    try:
        total = len(paginas)
        for i, pagina in enumerate(paginas):
            if abortar():
                raise ErrorArmado("Cancelado.")

            ruta = Path(pagina.ruta)
            if not ruta.is_file():
                raise ErrorArmado(
                    f"No se encuentra el archivo de la página {i + 1}:\n{ruta}")

            avisar(3 + int(i / total * 85),
                   f"Procesando la página {i + 1} de {total}…")

            if getattr(pagina, "es_pdf", pagina.origen == ORIGEN_PDF):
                clave = str(ruta)
                if clave not in lectores:
                    # A memoria, no desde el archivo: el destino puede ser
                    # el MISMO PDF que se está leyendo (guardar encima de
                    # lo que se abrió es lo más natural del mundo), y en
                    # Windows no se puede renombrar sobre un archivo que
                    # está abierto. Leerlo entero cuesta RAM proporcional
                    # al PDF y evita el problema de raíz.
                    lectores[clave] = _abrir_lector(ruta, ruta.read_bytes())
                lector = lectores[clave]
                paginas_origen = lector.pages            # type: ignore[attr-defined]
                if not 0 <= pagina.indice < len(paginas_origen):
                    raise ErrorArmado(
                        f"«{ruta.name}» ya no tiene la página "
                        f"{pagina.indice + 1}: ahora tiene "
                        f"{len(paginas_origen)}.")
                escritor.add_page(paginas_origen[pagina.indice])
            else:
                ruta_pdf = convertir_imagen_a_pdf(str(ruta), 0, calidad_)
                temporales.append(ruta_pdf)
                lector_img = PdfReader(ruta_pdf)
                lectores[ruta_pdf] = lector_img
                escritor.add_page(lector_img.pages[0])

            # El giro va sobre la copia del escritor, nunca sobre la página
            # del lector: si la misma página entra dos veces con rotaciones
            # distintas, mutar el original le pondría la última a ambas.
            # `rotate` acumula sobre el /Rotate que la página ya traía, que
            # es exactamente lo que se quiere: `rotacion` es un giro extra.
            if pagina.rotacion:
                escritor.pages[-1].rotate(int(pagina.rotacion))

        avisar(92, "Escribiendo el documento…")
        try:
            escritor.add_metadata({"/Producer": PRODUCTOR,
                                   "/Creator": PRODUCTOR})
        except Exception as e:                           # noqa: BLE001
            log.warning("No se pudieron escribir los metadatos: %s", e)

        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_name(destino.name + ".parcial")
        with open(parcial, "wb") as salida:
            escritor.write(salida)
        os.replace(parcial, destino)
        parcial = None

        log.info("PDF armado: %s (%d páginas, %d bytes)",
                 destino, total, destino.stat().st_size)
        avisar(100, "¡Listo!")
        return destino

    finally:
        for t in temporales:
            borrar_si_existe(t)
        if parcial is not None:
            borrar_si_existe(str(parcial))


def armar_varios(documentos: Sequence[tuple], *, cal=CALIDAD_DEFECTO,
                 progreso: Callable[[int, str], None] | None = None,
                 cancelado: Callable[[], bool] | None = None) -> list[Path]:
    """Escribe varios PDF de una, para dividir. Devuelve las rutas escritas.

    `documentos` son pares (páginas, destino). El progreso se reparte entre
    todos, así la barra avanza de 0 a 100 una sola vez y no N veces.

    Si uno falla, los que ya se escribieron **quedan**: son archivos
    válidos y borrarlos sería tirar trabajo bueno por un error posterior.
    El llamador se entera de cuáles alcanzó a hacer por la excepción.
    """
    avisar = progreso or (lambda *_: None)
    hechos: list[Path] = []
    cantidad = len(documentos) or 1

    for n, (paginas, destino) in enumerate(documentos):
        base = int(n / cantidad * 100)
        tramo = 100 / cantidad

        def avisar_tramo(pct: int, texto: str, _base=base, _tramo=tramo,
                         _n=n) -> None:
            avisar(min(100, _base + int(pct * _tramo / 100)),
                   f"Archivo {_n + 1} de {cantidad}: {texto}")

        try:
            hechos.append(armar_pdf(paginas, destino, cal=cal,
                                    progreso=avisar_tramo, cancelado=cancelado))
        except ErrorArmado as e:
            raise ErrorArmado(
                f"{e}\n\nSe alcanzaron a guardar {len(hechos)} de "
                f"{cantidad} archivos.") from e

    avisar(100, "¡Listo!")
    return hechos
