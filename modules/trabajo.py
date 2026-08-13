"""
modules/trabajo.py
============================================================
Modelo del trabajo de firma en curso.

Antes el estado vivía suelto en atributos de la ventana principal
(_pdf_activo, _pagina_activa) y cada fase recibía un int. Eso ataba
todo el flujo a "una página por sesión" y dejaba la validación
repartida entre las vistas.

Acá vive la lógica pura —sin Qt— de qué páginas se van a firmar, qué
imagen va en cada una y cuándo el trabajo está listo para guardarse.
Al no depender de la UI, se puede testear directamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Rotaciones admitidas para la imagen escaneada (grados horarios)
ROTACIONES_VALIDAS = (0, 90, 180, 270)


def formatear_paginas(paginas: list[int], *, base_1: bool = True) -> str:
    """Convierte una lista de índices en una etiqueta legible.

    Comprime los tramos consecutivos, que es como la gente lee un
    conjunto de páginas:
        [0,1,2,3]      → "1-4"
        [0,2,4]        → "1, 3, 5"
        [0,1,2,5,7,8]  → "1-3, 6, 8-9"
    """
    if not paginas:
        return "—"

    nums = sorted({int(p) + (1 if base_1 else 0) for p in paginas})
    tramos: list[str] = []
    inicio = anterior = nums[0]

    for n in nums[1:]:
        if n == anterior + 1:
            anterior = n
            continue
        tramos.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
        inicio = anterior = n
    tramos.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")

    return ", ".join(tramos)


def parsear_paginas(texto: str, total: int) -> list[int]:
    """Interpreta una expresión de páginas escrita por el usuario.

    Acepta "1, 3, 5-8" (base 1) y devuelve índices base 0, ordenados,
    sin duplicados y recortados al rango real del documento. Ignora en
    silencio los tramos mal escritos en vez de fallar: es una ayuda de
    entrada, no un parser estricto.
    """
    encontrados: set[int] = set()
    for parte in str(texto).replace(";", ",").split(","):
        parte = parte.strip()
        if not parte:
            continue
        try:
            if "-" in parte.lstrip("-"):
                desde_txt, hasta_txt = parte.split("-", 1)
                desde, hasta = int(desde_txt), int(hasta_txt)
                if desde > hasta:
                    desde, hasta = hasta, desde
                encontrados.update(range(desde, hasta + 1))
            else:
                encontrados.add(int(parte))
        except ValueError:
            continue

    return sorted(p - 1 for p in encontrados if 1 <= p <= total)


@dataclass
class TrabajoFirma:
    """Un PDF en proceso: qué páginas se firman y con qué imágenes.

    Invariantes que garantiza la clase:
      - `paginas` siempre ordenada, sin duplicados y dentro del rango
      - `imagenes` y `rotaciones` nunca tienen claves fuera de `paginas`
      - `rotaciones` sólo guarda múltiplos de 90 normalizados a 0-270
    """

    ruta_pdf: Path
    total_paginas: int = 0
    paginas: list[int] = field(default_factory=list)
    imagenes: dict[int, str] = field(default_factory=dict)
    rotaciones: dict[int, int] = field(default_factory=dict)

    # ── Selección de páginas ──────────────────────────────────────────
    def set_paginas(self, paginas) -> list[int]:
        """Fija las páginas a firmar, normalizando la entrada.

        Descarta las que caen fuera del documento y limpia las imágenes
        que hubieran quedado asignadas a páginas ya no seleccionadas.
        """
        limpias = sorted({
            int(p) for p in paginas
            if 0 <= int(p) < max(0, self.total_paginas)
        })
        self.paginas = limpias

        vigentes = set(limpias)
        self.imagenes = {p: r for p, r in self.imagenes.items() if p in vigentes}
        self.rotaciones = {p: g for p, g in self.rotaciones.items() if p in vigentes}
        return self.paginas

    def alternar_pagina(self, pagina: int) -> bool:
        """Agrega o quita una página. Devuelve True si quedó seleccionada."""
        seleccion = set(self.paginas)
        if pagina in seleccion:
            seleccion.discard(pagina)
            activa = False
        else:
            seleccion.add(pagina)
            activa = True
        self.set_paginas(seleccion)
        return activa

    # ── Imágenes ──────────────────────────────────────────────────────
    def asignar_imagen(self, pagina: int, ruta: str) -> None:
        """Asocia una imagen escaneada a una página seleccionada."""
        if pagina not in self.paginas:
            raise ValueError(
                f"La página {pagina + 1} no está entre las seleccionadas.")
        self.imagenes[pagina] = str(ruta)

    def quitar_imagen(self, pagina: int) -> None:
        self.imagenes.pop(pagina, None)
        self.rotaciones.pop(pagina, None)

    def rotar(self, pagina: int, grados: int = 90) -> int:
        """Acumula una rotación sobre la imagen de una página.

        Devuelve la rotación resultante (0/90/180/270).
        """
        if pagina not in self.imagenes:
            raise ValueError(
                f"La página {pagina + 1} todavía no tiene imagen asignada.")
        actual = self.rotaciones.get(pagina, 0)
        nueva = (actual + int(grados)) % 360
        if nueva % 90:
            raise ValueError("La rotación debe ser múltiplo de 90 grados.")
        if nueva:
            self.rotaciones[pagina] = nueva
        else:
            self.rotaciones.pop(pagina, None)
        return nueva

    def rotacion(self, pagina: int) -> int:
        return self.rotaciones.get(pagina, 0)

    # ── Estado ────────────────────────────────────────────────────────
    def paginas_pendientes(self) -> list[int]:
        """Páginas seleccionadas que todavía no tienen imagen."""
        return [p for p in self.paginas if p not in self.imagenes]

    def paginas_listas(self) -> list[int]:
        return [p for p in self.paginas if p in self.imagenes]

    def siguiente_pendiente(self, desde: int | None = None) -> int | None:
        """Próxima página sin imagen, recorriendo de forma circular.

        Permite que al terminar un escaneo el foco salte solo a la
        siguiente página que falta.
        """
        pendientes = self.paginas_pendientes()
        if not pendientes:
            return None
        if desde is None:
            return pendientes[0]
        posteriores = [p for p in pendientes if p > desde]
        return posteriores[0] if posteriores else pendientes[0]

    @property
    def completo(self) -> bool:
        """True cuando hay páginas elegidas y todas tienen imagen."""
        return bool(self.paginas) and not self.paginas_pendientes()

    @property
    def cantidad(self) -> int:
        return len(self.paginas)

    def etiqueta_paginas(self) -> str:
        return formatear_paginas(self.paginas)

    def descripcion_progreso(self) -> str:
        """Texto de estado del tipo '2 de 5 páginas listas'."""
        listas = len(self.paginas_listas())
        total = len(self.paginas)
        if not total:
            return "Sin páginas seleccionadas"
        if listas == total:
            plural = "s" if total != 1 else ""
            return f"{total} página{plural} lista{plural} para guardar"
        return f"{listas} de {total} páginas listas"

    def resumen(self, nombre_doc: str) -> str:
        """Resumen del documento para el cuerpo del correo."""
        plural = "s" if self.cantidad != 1 else ""
        return (
            f"Documento:              {nombre_doc}\n"
            f"Página{plural} reemplazada{plural}:   {self.etiqueta_paginas()}\n"
            f"Total páginas firmadas: {self.cantidad}"
        )
