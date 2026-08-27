"""
modules/documento_escaneado.py
============================================================
Modelo de dominio de la herramienta "Escanear a PDF".

Representa el documento que se va armando: una lista ordenada de páginas,
cada una con su imagen y su rotación. No sabe nada de Qt ni de escáneres;
sólo de qué páginas hay, en qué orden y cómo están giradas.

Está separado de la UI a propósito, igual que modules/trabajo.py:

  - se puede probar entero sin abrir una ventana ni tener un escáner,
  - la pantalla queda como una vista del modelo, sin lógica propia,
  - reordenar páginas —que es donde se cometen los errores de índices—
    tiene tests que lo cubren.

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

#: Extensiones que la herramienta acepta arrastrar o importar.
EXTENSIONES_IMAGEN = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")

#: Caracteres que Windows no admite en un nombre de archivo.
_PROHIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Nombres reservados por Windows: un archivo llamado así falla al crearse.
_RESERVADOS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass
class PaginaEscaneada:
    """Una página del documento en construcción."""

    id: int
    ruta: Path
    rotacion: int = 0
    #: True si la imagen es un temporal que la app creó y debe borrar al
    #: cerrar. Las importadas por el usuario no se tocan.
    temporal: bool = True
    origen: str = "escaner"          # "escaner" | "archivo"

    @property
    def nombre(self) -> str:
        return self.ruta.name

    @property
    def existe(self) -> bool:
        return self.ruta.is_file()


@dataclass
class DocumentoEscaneado:
    """Documento que se arma página por página.

    Uso típico:
        doc = DocumentoEscaneado()
        doc.agregar("/tmp/escaneo1.png")
        doc.agregar("/tmp/escaneo2.png")
        doc.rotar(1, 90)
        doc.mover(2, -1)
    """

    paginas: list[PaginaEscaneada] = field(default_factory=list)
    _siguiente_id: int = 1

    # ── Alta de páginas ───────────────────────────────────────────────────────

    def agregar(self, ruta: str | Path, *, rotacion: int = 0,
                temporal: bool = True, origen: str = "escaner",
                indice: int | None = None) -> PaginaEscaneada:
        """Agrega una página. Por defecto al final; con `indice`, ahí.

        Devuelve la página creada, para que la UI sepa qué id resaltar.
        """
        pagina = PaginaEscaneada(
            id=self._siguiente_id,
            ruta=Path(ruta),
            rotacion=_normalizar_rotacion(rotacion),
            temporal=temporal,
            origen=origen,
        )
        self._siguiente_id += 1
        if indice is None or indice >= len(self.paginas):
            self.paginas.append(pagina)
        else:
            self.paginas.insert(max(0, indice), pagina)
        return pagina

    def agregar_varias(self, rutas, *, temporal: bool = False,
                       origen: str = "archivo") -> list[PaginaEscaneada]:
        """Agrega varias imágenes de una, en el orden recibido."""
        return [self.agregar(r, temporal=temporal, origen=origen) for r in rutas]

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

    def pagina(self, id_pagina: int) -> PaginaEscaneada | None:
        i = self.indice_de(id_pagina)
        return self.paginas[i] if i >= 0 else None

    def faltantes(self) -> list[PaginaEscaneada]:
        """Páginas cuyo archivo ya no está en disco.

        Puede pasar si el temporal se limpió por fuera o si el usuario
        movió una imagen importada. Conviene avisar antes de guardar y no
        reventar a mitad de camino.
        """
        return [p for p in self.paginas if not p.existe]

    def rutas_temporales(self) -> list[Path]:
        """Archivos que la app creó y le toca borrar al cerrar."""
        return [p.ruta for p in self.paginas if p.temporal]

    # ── Modificación ──────────────────────────────────────────────────────────

    def quitar(self, id_pagina: int) -> PaginaEscaneada | None:
        """Saca una página del documento y la devuelve (o None si no estaba)."""
        i = self.indice_de(id_pagina)
        if i < 0:
            return None
        return self.paginas.pop(i)

    def rotar(self, id_pagina: int, grados: int) -> bool:
        """Gira una página en incrementos de 90°, acumulando sobre lo que ya tenía."""
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
        """Nombre por defecto del PDF: 'Escaneo 2026-08-27 14-30.pdf'.

        Con guiones en vez de dos puntos porque Windows no admite ':' en
        un nombre de archivo.
        """
        ahora = momento or _dt.datetime.now()
        return f"Escaneo {ahora:%Y-%m-%d %H-%M}.pdf"


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
    """True si la extensión está entre las que la herramienta sabe leer."""
    return Path(ruta).suffix.lower() in EXTENSIONES_IMAGEN


def filtrar_imagenes(rutas) -> list[str]:
    """Deja sólo las rutas que son imágenes, conservando el orden.

    Lo usa la zona de arrastrar y soltar: si alguien suelta una carpeta
    entera, se toman las imágenes y se ignora el resto en silencio.
    """
    return [str(r) for r in rutas if es_imagen(r)]
