"""
modules/documento.py
============================================================
Modelo de dominio de las herramientas que arman un PDF página por página.

Antes esto era `documento_escaneado.py` y una página era siempre una
imagen recién salida del escáner. Ahora una página puede venir de tres
lados —el escáner, una imagen del disco, o una página de un PDF que ya
existe— y las dos herramientas que arman PDFs comparten el mismo modelo:

    Escanear a PDF     empieza vacío (o abriendo un PDF para agregarle
                       páginas al final) y suma hojas del escáner
    Unir y dividir     empieza abriendo uno o varios PDFs y se dedica a
                       reordenar, quitar y separar

Son dos pantallas distintas porque el trabajo se siente distinto, pero
por debajo es la misma lista ordenada de páginas. Sumar un origen nuevo
(una foto del celular, un TIFF multipágina) es agregar un valor a
`ORIGENES` y enseñarle a leerlo a quien renderiza; el modelo no cambia.

Sigue sin saber nada de Qt, de PyMuPDF ni de escáneres: sólo de qué
páginas hay, de dónde salió cada una, en qué orden van y cómo están
giradas. Eso permite probar entero el reordenamiento —que es donde se
cometen los errores de índices— sin abrir una ventana.

Las páginas se identifican por un id estable, no por su posición: la
posición cambia cada vez que se reordena, y usarla como identificador es
la receta para borrar la página equivocada.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Rotaciones admitidas, en grados en sentido horario.
ROTACIONES = (0, 90, 180, 270)

#: Extensiones de imagen que las herramientas aceptan.
EXTENSIONES_IMAGEN = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")

#: Extensiones de documento.
EXTENSIONES_PDF = (".pdf",)

#: De dónde salió una página. El valor viaja en `Pagina.origen` y decide
#: cómo se lee la página para mostrarla y cómo se la escribe al guardar.
ORIGEN_ESCANER = "escaner"
ORIGEN_IMAGEN = "imagen"
ORIGEN_PDF = "pdf"
ORIGENES = (ORIGEN_ESCANER, ORIGEN_IMAGEN, ORIGEN_PDF)

#: Cómo nombrar cada origen en la interfaz.
_ETIQUETA_ORIGEN = {
    ORIGEN_ESCANER: "Escaneada",
    ORIGEN_IMAGEN: "Imagen",
    ORIGEN_PDF: "PDF",
}

#: Caracteres que Windows no admite en un nombre de archivo.
_PROHIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Nombres reservados por Windows: un archivo llamado así falla al crearse.
_RESERVADOS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass
class Pagina:
    """Una página del documento en construcción.

    `ruta` es el archivo de origen e `indice` la página dentro de ese
    archivo. Para una imagen el índice es siempre 0 y no significa nada;
    para un PDF es la página (contando desde 0) que hay que copiar.
    """

    id: int
    ruta: Path
    #: Giro que el usuario le aplicó, en grados horarios. Es **adicional**
    #: a lo que la página ya trae: un PDF puede tener su propia rotación
    #: guardada adentro (/Rotate) y una foto puede venir de costado por el
    #: acelerómetro. Esos giros los aplica quien lee el archivo; acá sólo
    #: se guarda lo que se pidió encima. Sumarlos dos veces deja las
    #: páginas de lado, que es justo lo que se está tratando de arreglar.
    rotacion: int = 0
    #: True si el archivo es un temporal que la app creó y le toca borrar
    #: al cerrar. Lo que el usuario abrió o importó no se toca nunca.
    temporal: bool = True
    origen: str = ORIGEN_ESCANER
    #: Página dentro del archivo, contando desde 0. Sólo tiene sentido
    #: cuando `origen` es "pdf".
    indice: int = 0

    @property
    def nombre(self) -> str:
        return self.ruta.name

    @property
    def existe(self) -> bool:
        return self.ruta.is_file()

    @property
    def es_pdf(self) -> bool:
        return self.origen == ORIGEN_PDF

    @property
    def es_imagen(self) -> bool:
        return self.origen in (ORIGEN_ESCANER, ORIGEN_IMAGEN)

    @property
    def clave(self) -> tuple:
        """Identifica el *contenido* de la página, no la página.

        Dos entradas distintas de la lista que apunten a la misma página
        del mismo PDF con la misma rotación se ven idénticas, así que
        pueden compartir la miniatura ya renderizada. Por eso el id no
        entra en la clave: entrarían dos veces al cache lo mismo.
        """
        return (str(self.ruta), self.indice, self.rotacion)

    def etiqueta_origen(self) -> str:
        """Cómo nombrar el origen de esta página en la interfaz."""
        return _ETIQUETA_ORIGEN.get(self.origen, self.origen)

    def descripcion(self) -> str:
        """Texto corto para el tooltip de la fila: de dónde salió."""
        if self.es_pdf:
            return f"{self.nombre} · página {self.indice + 1}"
        return self.nombre


@dataclass
class Documento:
    """Documento que se arma página por página.

    Uso típico:
        doc = Documento()
        doc.agregar_pdf("Contrato.pdf", 4)     # las 4 páginas que ya tiene
        doc.agregar("/tmp/escaneo1.png")       # una hoja más del escáner
        doc.mover(1, +1)
    """

    paginas: list[Pagina] = field(default_factory=list)
    #: Nombre base para sugerir al guardar. Lo completa quien abre un PDF
    #: para que el archivo resultante se parezca al de partida en vez de
    #: llamarse "Escaneo <fecha>".
    base_nombre: str = ""
    _siguiente_id: int = 1

    # ── Alta de páginas ───────────────────────────────────────────────────────

    def agregar(self, ruta: str | Path, *, rotacion: int = 0,
                temporal: bool = True, origen: str = ORIGEN_ESCANER,
                indice_pagina: int = 0,
                indice: int | None = None) -> Pagina:
        """Agrega una página. Por defecto al final; con `indice`, ahí.

        Devuelve la página creada, para que la UI sepa cuál resaltar.
        """
        pagina = Pagina(
            id=self._siguiente_id,
            ruta=Path(ruta),
            rotacion=_normalizar_rotacion(rotacion),
            temporal=temporal,
            origen=origen,
            indice=max(0, int(indice_pagina)),
        )
        self._siguiente_id += 1
        if indice is None or indice >= len(self.paginas):
            self.paginas.append(pagina)
        else:
            self.paginas.insert(max(0, indice), pagina)
        return pagina

    def agregar_varias(self, rutas, *, temporal: bool = False,
                       origen: str = ORIGEN_IMAGEN) -> list[Pagina]:
        """Agrega varias imágenes de una, en el orden recibido."""
        return [self.agregar(r, temporal=temporal, origen=origen) for r in rutas]

    def agregar_pdf(self, ruta: str | Path, cantidad: int, *,
                    rotaciones=None, indice: int | None = None) -> list[Pagina]:
        """Agrega las `cantidad` páginas de un PDF, en orden.

        El modelo no abre el archivo —no importa pypdf ni PyMuPDF a
        propósito—, así que la cantidad la pasa quien sí lo abrió.

        `rotaciones` es un giro *extra* por página, no la rotación que el
        PDF ya trae adentro: esa viaja en el archivo y la aplica quien lo
        lee. Sirve para abrir un documento entero de costado con una sola
        pasada, no para copiar lo que ya estaba.

        El archivo se marca como NO temporal: es del usuario, y borrarlo al
        cerrar sería destruir su documento.
        """
        giros = list(rotaciones or ())
        creadas = []
        for i in range(max(0, int(cantidad))):
            creadas.append(self.agregar(
                ruta,
                rotacion=giros[i] if i < len(giros) else 0,
                temporal=False,
                origen=ORIGEN_PDF,
                indice_pagina=i,
                indice=None if indice is None else indice + i,
            ))
        return creadas

    # ── Consulta ──────────────────────────────────────────────────────────────

    @property
    def total(self) -> int:
        return len(self.paginas)

    @property
    def vacio(self) -> bool:
        return not self.paginas

    def indice_de(self, id_pagina: int) -> int:
        """Posición actual de una página, o -1 si ya no está."""
        for i, p in enumerate(self.paginas):
            if p.id == id_pagina:
                return i
        return -1

    def pagina(self, id_pagina: int) -> Pagina | None:
        i = self.indice_de(id_pagina)
        return self.paginas[i] if i >= 0 else None

    def faltantes(self) -> list[Pagina]:
        """Páginas cuyo archivo ya no está en disco.

        Puede pasar si el temporal se limpió por fuera o si el usuario movió
        el PDF que había abierto. Conviene avisar antes de guardar y no
        reventar a mitad de camino.
        """
        return [p for p in self.paginas if not p.existe]

    def rutas_temporales(self) -> list[Path]:
        """Archivos que la app creó y le toca borrar al cerrar."""
        return [p.ruta for p in self.paginas if p.temporal]

    def origenes(self) -> set[str]:
        """Qué clases de página hay adentro."""
        return {p.origen for p in self.paginas}

    @property
    def tiene_pdf(self) -> bool:
        return any(p.es_pdf for p in self.paginas)

    @property
    def mixto(self) -> bool:
        """True si conviven páginas de PDF con imágenes.

        Quien arma el archivo final lo usa para decidir el camino: sólo
        páginas de PDF se copian tal cual y el texto se conserva; en cuanto
        hay una imagen hace falta mezclar los dos caminos.
        """
        return self.tiene_pdf and any(p.es_imagen for p in self.paginas)

    def archivos_pdf(self) -> list[Path]:
        """Los PDF de los que salió alguna página, sin repetir y en orden."""
        vistos: dict[str, Path] = {}
        for p in self.paginas:
            if p.es_pdf:
                vistos.setdefault(str(p.ruta), p.ruta)
        return list(vistos.values())

    # ── Modificación ──────────────────────────────────────────────────────────

    def quitar(self, id_pagina: int) -> Pagina | None:
        """Saca una página del documento y la devuelve (o None si no estaba)."""
        i = self.indice_de(id_pagina)
        if i < 0:
            return None
        return self.paginas.pop(i)

    def quitar_varias(self, ids) -> list[Pagina]:
        """Saca varias páginas de una. Devuelve las que estaban.

        Borrar de a una desde la UI funciona, pero recalcula la lista N
        veces; y sobre todo: quitar por id evita el clásico de iterar por
        posición mientras la lista se acorta debajo.
        """
        pedidos = set(ids)
        sacadas = [p for p in self.paginas if p.id in pedidos]
        if sacadas:
            self.paginas = [p for p in self.paginas if p.id not in pedidos]
        return sacadas

    def rotar(self, id_pagina: int, grados: int) -> bool:
        """Gira una página en incrementos de 90°, sobre lo que ya tenía."""
        p = self.pagina(id_pagina)
        if p is None:
            return False
        p.rotacion = _normalizar_rotacion(p.rotacion + grados)
        return True

    def rotar_todas(self, grados: int) -> None:
        for p in self.paginas:
            p.rotacion = _normalizar_rotacion(p.rotacion + grados)

    def mover(self, id_pagina: int, desplazamiento: int) -> bool:
        """Sube (-1) o baja (+1) una página. Devuelve False si no se movió.

        Los extremos no dan la vuelta: la primera página no salta al final
        al pedirle "subir". Eso desconcierta más de lo que ayuda.
        """
        i = self.indice_de(id_pagina)
        if i < 0:
            return False
        destino = i + desplazamiento
        if destino < 0 or destino >= len(self.paginas) or destino == i:
            return False
        self.paginas.insert(destino, self.paginas.pop(i))
        return True

    def mover_a(self, id_pagina: int, indice: int) -> bool:
        """Lleva una página a una posición concreta (para arrastrar y soltar)."""
        i = self.indice_de(id_pagina)
        if i < 0:
            return False
        destino = max(0, min(indice, len(self.paginas) - 1))
        if destino == i:
            return False
        self.paginas.insert(destino, self.paginas.pop(i))
        return True

    def invertir(self) -> None:
        """Da vuelta el orden. Útil cuando el escáner entrega el taco al revés."""
        self.paginas.reverse()

    def limpiar(self) -> None:
        self.paginas.clear()
        self.base_nombre = ""

    # ── Subconjuntos (dividir) ────────────────────────────────────────────────

    def subconjunto(self, indices) -> "Documento":
        """Un documento nuevo con las páginas de esas posiciones (0-based).

        Es lo que necesita "dividir": el original queda intacto y cada
        trozo es un `Documento` que se guarda con el mismo motor que usa
        cualquier otro. Las posiciones fuera de rango se ignoran, así un
        rango escrito de más no tira todo abajo.

        Las páginas se copian, no se comparten: mover una página en el
        trozo no debe reordenar el documento de origen.
        """
        trozo = Documento(base_nombre=self.base_nombre)
        for i in indices:
            if 0 <= i < len(self.paginas):
                p = self.paginas[i]
                trozo.agregar(p.ruta, rotacion=p.rotacion,
                              temporal=False,          # el trozo no manda a borrar
                              origen=p.origen, indice_pagina=p.indice)
        return trozo

    def partir_cada(self, cantidad: int) -> list["Documento"]:
        """Corta el documento en trozos de `cantidad` páginas.

        El último trozo se queda con el resto: partir 7 páginas de a 3 da
        3 + 3 + 1, no 3 + 3 + 3 con dos páginas inventadas.
        """
        n = max(1, int(cantidad))
        return [self.subconjunto(range(i, min(i + n, self.total)))
                for i in range(0, self.total, n)]

    # ── Presentación ──────────────────────────────────────────────────────────

    def descripcion(self) -> str:
        """Resumen corto para la barra de estado."""
        if not self.paginas:
            return "Sin páginas todavía"
        if len(self.paginas) == 1:
            return "1 página"
        return f"{len(self.paginas)} páginas"

    def resumen_rotaciones(self) -> str:
        """Cuántas páginas quedaron giradas (0 se omite)."""
        giradas = sum(1 for p in self.paginas if p.rotacion)
        if not giradas:
            return ""
        return f"{giradas} girada{'s' if giradas != 1 else ''}"

    def nombre_sugerido(self, momento: _dt.datetime | None = None) -> str:
        """Nombre por defecto del PDF al guardar.

        Si el documento arrancó de un archivo, se parte de su nombre y se
        le suma "(editado)": guardar encima del original por accidente,
        con páginas quitadas, es una pérdida de datos silenciosa.

        Si arrancó vacío, se usa la fecha: 'Escaneo 2026-08-27 14-30.pdf'.
        Con guiones en vez de dos puntos porque Windows no admite ':' en un
        nombre de archivo.
        """
        if self.base_nombre:
            return con_extension_pdf(f"{self.base_nombre} (editado)")
        ahora = momento or _dt.datetime.now()
        return f"Escaneo {ahora:%Y-%m-%d %H-%M}.pdf"

    def nombre_de_trozo(self, numero: int, total: int) -> str:
        """Nombre de una parte al dividir: 'Contrato (parte 2 de 5).pdf'.

        El número va con ceros a la izquierda cuando hacen falta, para que
        el explorador de Windows los ordene bien: sin eso, la parte 10 se
        mete entre la 1 y la 2.
        """
        base = self.base_nombre or "Documento"
        ancho = len(str(max(1, total)))
        return con_extension_pdf(f"{base} (parte {numero:0{ancho}d} de {total})")


# ═══════════════════════════════════════════════════════════════════════════════
#  Funciones sueltas
# ═══════════════════════════════════════════════════════════════════════════════

def _normalizar_rotacion(grados: int) -> int:
    """Lleva cualquier ángulo a 0, 90, 180 o 270."""
    return int(grados) % 360 // 90 * 90


def sanear_nombre(nombre: str, *, defecto: str = "Escaneo") -> str:
    """Convierte un texto en un nombre de archivo que Windows acepte.

    Quita los caracteres prohibidos, los puntos y espacios del final (que
    Windows recorta en silencio, dejando un nombre distinto al que el
    usuario escribió) y evita los nombres reservados tipo CON o LPT1.
    """
    limpio = _PROHIBIDOS.sub("", str(nombre)).strip()
    limpio = limpio.rstrip(". ")
    if not limpio:
        return defecto
    if limpio.split(".")[0].upper() in _RESERVADOS:
        limpio = f"_{limpio}"
    return limpio[:120]


def con_extension_pdf(nombre: str) -> str:
    """Garantiza que el nombre termine en .pdf, sin duplicar la extensión."""
    limpio = sanear_nombre(nombre)
    if limpio.lower().endswith(".pdf"):
        return limpio
    return f"{limpio}.pdf"


def es_imagen(ruta: str | Path) -> bool:
    """True si la extensión está entre las imágenes que sabemos leer."""
    return Path(ruta).suffix.lower() in EXTENSIONES_IMAGEN


def es_pdf(ruta: str | Path) -> bool:
    return Path(ruta).suffix.lower() in EXTENSIONES_PDF


def filtrar_imagenes(rutas) -> list[str]:
    """Deja sólo las rutas que son imágenes, conservando el orden."""
    return [str(r) for r in rutas if es_imagen(r)]


def filtrar_pdfs(rutas) -> list[str]:
    return [str(r) for r in rutas if es_pdf(r)]


def filtrar_soportados(rutas) -> list[str]:
    """Imágenes y PDF, en el orden en que llegaron.

    Lo usa la zona de arrastrar y soltar: si alguien suelta una carpeta
    entera, se toma lo que sabemos abrir y se ignora el resto en silencio.
    """
    return [str(r) for r in rutas if es_imagen(r) or es_pdf(r)]


# ── Rangos de páginas ─────────────────────────────────────────────────────────

def parsear_rangos(texto: str, total: int) -> list[int]:
    """Convierte "1-3, 5, 9-7" en posiciones 0-based: [0,1,2,4,8,7,6].

    Lo que el usuario escribe es 1-based porque es lo que ve en pantalla;
    lo que devuelve es 0-based porque es lo que usa el modelo. Traducir en
    un solo lugar evita el error de restar uno dos veces.

    Un rango al revés (9-7) se expande al revés: es una forma cómoda de
    invertir un tramo, y prohibirlo no aportaría nada.

    Lanza ValueError con un mensaje que se le puede mostrar al usuario tal
    cual, así la pantalla no tiene que armar el texto.
    """
    if total <= 0:
        raise ValueError("El documento no tiene páginas.")

    limpio = (texto or "").replace(";", ",").strip()
    if not limpio:
        raise ValueError("Escribí qué páginas querés, por ejemplo: 1-3, 5")

    indices: list[int] = []
    for parte in (p.strip() for p in limpio.split(",")):
        if not parte:
            continue
        m = re.fullmatch(r"(\d+)\s*(?:[-–—]\s*(\d+))?", parte)
        if m is None:
            raise ValueError(
                f'No entiendo "{parte}". Usá números y rangos: 1-3, 5')

        desde = int(m.group(1))
        hasta = int(m.group(2)) if m.group(2) else desde
        for n in (desde, hasta):
            if n < 1 or n > total:
                raise ValueError(
                    f"La página {n} no existe: el documento tiene {total}.")

        paso = 1 if hasta >= desde else -1
        indices.extend(range(desde - 1, hasta - 1 + paso, paso))

    if not indices:
        raise ValueError("Escribí qué páginas querés, por ejemplo: 1-3, 5")

    # Sin repetir, conservando el orden en que se escribieron: pedir
    # "1-3, 2" no debe meter la página 2 dos veces en el PDF.
    vistos: dict[int, None] = {}
    for i in indices:
        vistos.setdefault(i, None)
    return list(vistos)


def formatear_rangos(indices) -> str:
    """El camino inverso, para mostrar una selección: [0,1,2,4] → "1-3, 5".

    Sólo agrupa tramos que van hacia adelante; una selección desordenada
    se muestra tal cual, que es más honesto que inventarle un orden.
    """
    numeros = [i + 1 for i in indices]
    if not numeros:
        return ""

    partes: list[str] = []
    inicio = anterior = numeros[0]
    for n in numeros[1:]:
        if n == anterior + 1:
            anterior = n
            continue
        partes.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
        inicio = anterior = n
    partes.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
    return ", ".join(partes)
