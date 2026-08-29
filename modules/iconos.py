"""
modules/iconos.py
============================================================
Iconografía vectorial de la aplicación.

Por qué existe
--------------
La UI usaba emojis (📄, ⚙, 👁, ☀/🌙…) como iconos. En Windows eso depende
de que la fuente del sistema tenga ese glifo: si no lo tiene, el emoji se
degrada a un punto, a una barra o directamente a un cuadro vacío. Es
exactamente lo que pasaba: ⚙ se veía bien, 👁 salía como una raya y 🌙
como un punto, según la máquina y la versión de Segoe UI Emoji.

Acá los iconos se **dibujan**, no se escriben: son trazos SVG embebidos en
este archivo, renderizados con QSvgRenderer. Eso los vuelve:

  - independientes de la fuente instalada (se ven igual en toda máquina),
  - del color del tema (se les inyecta el color al renderizar),
  - nítidos en pantallas HiDPI (se rasterizan al devicePixelRatio real),
  - sin archivos sueltos que empaquetar: no hay assets que se puedan
    perder en el bundle de PyInstaller.

Organización del módulo
-----------------------
La primera mitad —el catálogo y `svg_documento()`— es Python puro, sin
Qt: así el CI liviano puede verificar que el catálogo esté sano y que
todos los nombres que usa la UI existan. La segunda mitad envuelve eso en
QIcon/QPixmap y sólo se activa si PyQt6 está disponible.

Uso:
    from modules import iconos
    boton.setIcon(iconos.icono("carpeta", 18))
    lbl.setPixmap(iconos.pixmap("alerta", 24, color="danger"))
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════════════════════════
#  Catálogo — Python puro, sin dependencias
# ═══════════════════════════════════════════════════════════════════════════════

#: Grosor de trazo por defecto, en unidades del viewBox de 24×24.
GROSOR = 1.7

#: Lienzo de referencia. Todos los trazos se dibujan en esta caja.
VIEWBOX = 24


@dataclass(frozen=True)
class Icono:
    """Un icono: uno o más subtrazos SVG sobre un lienzo de 24×24."""

    trazos: tuple[str, ...]
    relleno: bool = False           # True → figura sólida en vez de contorno
    grosor: float = GROSOR
    #: Trazos extra que se pintan siempre rellenos (puntos, marcas).
    puntos: tuple[str, ...] = field(default_factory=tuple)


def _i(*trazos: str, **kw) -> Icono:
    return Icono(trazos=trazos, **kw)


CATALOGO: dict[str, Icono] = {
    # ── Documentos y archivos ─────────────────────────────────────────────────
    "documento": _i(
        "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z",
        "M14 3v5h5",
    ),
    "documento-texto": _i(
        "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z",
        "M14 3v5h5",
        "M9 13h6",
        "M9 17h4",
    ),
    "documento-firmado": _i(
        "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z",
        "M14 3v5h5",
        "M7.8 17c1.3 0 1.6-6.6 3.3-6.6 1 0 .6 4.6 1.7 4.6 1 0 1.2-2.2 2.2-2.2"
        " .8 0 .7 1.4 1.5 1.4",
    ),
    "documento-mas": _i(
        "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z",
        "M14 3v5h5",
        "M12 18v-6",
        "M9 15h6",
    ),
    "documentos": _i(
        "M9 8h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2z",
        "M5 16H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1",
    ),
    "carpeta": _i(
        "M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.5a2 2 0 0 1-1.6-.8L9.6 3.8"
        "A2 2 0 0 0 8 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z",
    ),
    "carpeta-abierta": _i(
        "M6 14.5l1.4-2.8A2 2 0 0 1 9.2 10.6H22l-2.4 7.2a2 2 0 0 1-1.9 1.4H4"
        "a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.7.9l.8 1.2"
        "a2 2 0 0 0 1.7.9H18a2 2 0 0 1 2 2v2.1",
    ),
    "imagen": _i(
        "M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z",
        "M9 10.5a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z",
        "M21 15.5l-4.6-4.6L5.5 21.8",
    ),
    "capas": _i(
        "M12 2.5L2.5 7 12 11.5 21.5 7 12 2.5z",
        "M2.5 16.5L12 21l9.5-4.5",
        "M2.5 11.8L12 16.3l9.5-4.5",
    ),
    # Tijera: los dos filos se cruzan en el centro y los mangos son
    # circunferencias abajo. Se lee como "cortar" a 16 px, que es donde
    # vive: el botón de dividir.
    "tijera": _i(
        "M6.5 3.2L15.5 15.6",
        "M17.5 3.2L8.5 15.6",
        "M6 21a2.6 2.6 0 1 1 0-5.2 2.6 2.6 0 0 1 0 5.2z",
        "M18 21a2.6 2.6 0 1 1 0-5.2 2.6 2.6 0 0 1 0 5.2z",
    ),
    # Unir: dos ramas que confluyen en un solo tronco con punta de flecha.
    # La primera versión eran dos flechas cruzándose, y se leía "mezclar
    # al azar" —el icono de shuffle de cualquier reproductor— que es
    # justo lo contrario de lo que hace el botón.
    "unir": _i(
        "M3.5 6.5h6l3.5 5.5",
        "M3.5 17.5h6l3.5-5.5",
        "M13 12h7.5",
        "M17.5 8.5l3.5 3.5-3.5 3.5",
    ),

    # ── Dispositivos ──────────────────────────────────────────────────────────
    "impresora": _i(
        "M6.5 9.5V3.5h11v6",
        "M6.5 18H4.5a2 2 0 0 1-2-2v-4.5a2 2 0 0 1 2-2h15a2 2 0 0 1 2 2V16"
        "a2 2 0 0 1-2 2h-2",
        "M6.5 14.5h11v6h-11z",
    ),
    "escaner": _i(
        "M3 7.5V5.5a2 2 0 0 1 2-2h2",
        "M17 3.5h2a2 2 0 0 1 2 2v2",
        "M21 16.5v2a2 2 0 0 1-2 2h-2",
        "M7 20.5H5a2 2 0 0 1-2-2v-2",
        "M3.5 12h17",
    ),

    # ── Acciones ──────────────────────────────────────────────────────────────
    "firma": _i(
        "M3 15.5c3 0 3.5-9 6.2-9 1.4 0 1.3 3 1 5.6-.3 2.4-.2 4.4 1.3 4.4"
        " 2 0 2.6-3.5 4.2-3.5 1.3 0 1.2 2.2 2.4 2.2.8 0 1.4-.5 1.9-1.2",
        "M3 20.5h18",
    ),
    "lapiz": _i(
        "M19.5 4.5a2.6 2.6 0 0 0-3.7 0L4.5 15.8 3.5 20.5l4.7-1 11.3-11.3"
        "a2.6 2.6 0 0 0 0-3.7z",
        "M14.5 6.5l3.5 3.5",
    ),
    "ojo": _i(
        "M2.2 12S6 5.5 12 5.5 21.8 12 21.8 12 18 18.5 12 18.5 2.2 12 2.2 12z",
        "M12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z",
    ),
    "guardar": _i(
        "M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z",
        "M17 21v-8H7v8",
        "M7 3v5h7",
    ),
    "descargar": _i(
        "M21 15.5V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3.5",
        "M7.5 10.5L12 15l4.5-4.5",
        "M12 15V3",
    ),
    "sobre": _i(
        "M4 4.5h16a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2z",
        "M21.5 6.2L12 13 2.5 6.2",
    ),
    "basura": _i(
        "M3.5 6h17",
        "M8.5 6V4.4a1.4 1.4 0 0 1 1.4-1.4h4.2a1.4 1.4 0 0 1 1.4 1.4V6",
        "M18.5 6l-.9 13.2a2 2 0 0 1-2 1.8H8.4a2 2 0 0 1-2-1.8L5.5 6",
        "M10 10.5v6",
        "M14 10.5v6",
    ),
    "rotar-der": _i(
        "M20.5 4v5.5H15",
        "M20.5 13a8.5 8.5 0 1 1-2.6-7.1l2.6 2.4",
    ),
    "rotar-izq": _i(
        "M3.5 4v5.5H9",
        "M3.5 13a8.5 8.5 0 1 0 2.6-7.1L3.5 8.3",
    ),
    "refrescar": _i(
        "M21.5 4.5v5.5H16",
        "M2.5 19.5V14H8",
        "M4.6 9.5a8 8 0 0 1 13.2-3L21.5 10",
        "M19.4 14.5a8 8 0 0 1-13.2 3L2.5 14",
    ),
    "buscar": _i(
        "M11 4.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13z",
        "M20.5 20.5l-4.9-4.9",
    ),
    "engranaje": _i(
        "M12 8.6a3.4 3.4 0 1 1 0 6.8 3.4 3.4 0 0 1 0-6.8z",
        "M19.1 14.4a1.5 1.5 0 0 0 .3 1.7l.1.1a1.9 1.9 0 1 1-2.6 2.6l-.1-.1"
        "a1.5 1.5 0 0 0-1.7-.3 1.5 1.5 0 0 0-.9 1.4v.2a1.9 1.9 0 1 1-3.8 0v-.1"
        "a1.5 1.5 0 0 0-1-1.4 1.5 1.5 0 0 0-1.7.3l-.1.1a1.9 1.9 0 1 1-2.6-2.6"
        "l.1-.1a1.5 1.5 0 0 0 .3-1.7 1.5 1.5 0 0 0-1.4-.9h-.2a1.9 1.9 0 1 1 0-3.8"
        "h.1a1.5 1.5 0 0 0 1.4-1 1.5 1.5 0 0 0-.3-1.7l-.1-.1a1.9 1.9 0 1 1 2.6-2.6"
        "l.1.1a1.5 1.5 0 0 0 1.7.3h.1a1.5 1.5 0 0 0 .9-1.4v-.2a1.9 1.9 0 1 1 3.8 0"
        "v.1a1.5 1.5 0 0 0 .9 1.4 1.5 1.5 0 0 0 1.7-.3l.1-.1a1.9 1.9 0 1 1 2.6 2.6"
        "l-.1.1a1.5 1.5 0 0 0-.3 1.7v.1a1.5 1.5 0 0 0 1.4.9h.2a1.9 1.9 0 1 1 0 3.8"
        "h-.1a1.5 1.5 0 0 0-1.4.9z",
    ),
    "abrir-externo": _i(
        "M18 13.5V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5.5",
        "M15 3h6v6",
        "M10 14L21 3",
    ),
    "copiar": _i(
        "M9 9h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2z",
        "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1",
    ),

    # ── Navegación y controles ────────────────────────────────────────────────
    "mas": _i("M12 5v14", "M5 12h14"),
    "menos": _i("M5 12h14"),
    "cerrar": _i("M18 6L6 18", "M6 6l12 12"),
    "check": _i("M20 6.5L9.2 17.3 4 12.1"),
    "flecha-der": _i("M4.5 12h15", "M13 5.5l6.5 6.5-6.5 6.5"),
    "flecha-izq": _i("M19.5 12h-15", "M11 18.5L4.5 12 11 5.5"),
    "chevron-der": _i("M9 5.5l6.5 6.5L9 18.5"),
    "chevron-izq": _i("M15 5.5L8.5 12 15 18.5"),
    "chevron-abajo": _i("M5.5 9l6.5 6.5L18.5 9"),
    "arriba": _i("M12 19.5v-15", "M5.5 11L12 4.5l6.5 6.5"),
    "abajo": _i("M12 4.5v15", "M18.5 13L12 19.5 5.5 13"),
    "cuadricula": _i(
        "M3.5 3.5h7v7h-7z",
        "M13.5 3.5h7v7h-7z",
        "M13.5 13.5h7v7h-7z",
        "M3.5 13.5h7v7h-7z",
    ),
    "casa": _i(
        "M3 9.6L12 2.5l9 7.1V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
        "M9.5 21v-8h5v8",
    ),
    "mover": _i(
        "M9 6h.01", "M9 12h.01", "M9 18h.01",
        "M15 6h.01", "M15 12h.01", "M15 18h.01",
        grosor=2.4,
    ),

    # ── Estado ────────────────────────────────────────────────────────────────
    "check-circulo": _i(
        "M21.5 11.1V12a9.5 9.5 0 1 1-5.6-8.7",
        "M21.5 5L12 14.5l-2.8-2.8",
    ),
    "alerta": _i(
        "M10.3 4L2.2 17.9A2 2 0 0 0 3.9 21h16.2a2 2 0 0 0 1.7-3.1L13.7 4"
        "a2 2 0 0 0-3.4 0z",
        "M12 9.5v4",
        "M12 17.2h.01",
    ),
    "error-circulo": _i(
        "M12 2.5a9.5 9.5 0 1 1 0 19 9.5 9.5 0 0 1 0-19z",
        "M15 9l-6 6",
        "M9 9l6 6",
    ),
    "info": _i(
        "M12 2.5a9.5 9.5 0 1 1 0 19 9.5 9.5 0 0 1 0-19z",
        "M12 16.5v-5",
        "M12 8h.01",
    ),
    "bombilla": _i(
        "M9.5 18.5h5",
        "M10.5 21.5h3",
        "M15.1 14.5c0.3-1.1 0.9-1.9 1.6-2.6A5.5 5.5 0 1 0 7.3 8"
        " c0 1.5 0.6 2.9 1.6 3.9 0.7 0.7 1.2 1.5 1.4 2.6",
    ),
    "reloj": _i(
        "M12 2.5a9.5 9.5 0 1 1 0 19 9.5 9.5 0 0 1 0-19z",
        "M12 6.5V12l3.5 2.2",
    ),
    "chispa": _i(
        "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z",
        "M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z",
        relleno=True,
    ),
    "punto": _i("M12 7a5 5 0 1 1 0 10 5 5 0 0 1 0-10z", relleno=True),

    # ── Tema ──────────────────────────────────────────────────────────────────
    "sol": _i(
        "M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8z",
        "M12 2.2v2.1", "M12 19.7v2.1",
        "M4.9 4.9l1.5 1.5", "M17.6 17.6l1.5 1.5",
        "M2.2 12h2.1", "M19.7 12h2.1",
        "M4.9 19.1l1.5-1.5", "M17.6 6.4l1.5-1.5",
    ),
    "luna": _i("M21 12.9A9 9 0 1 1 11.1 3 7 7 0 0 0 21 12.9z"),
}

#: Alias legibles para no atar el código a un nombre de dibujo concreto.
ALIAS: dict[str, str] = {
    "editar": "lapiz",
    "borrar": "basura",
    "quitar": "cerrar",
    "correo": "sobre",
    "vista-previa": "ojo",
    "ajustes": "engranaje",
    "actualizar": "descargar",
    "listo": "check-circulo",
    "advertencia": "alerta",
    "error": "error-circulo",
    "consejo": "bombilla",
    "escanear": "escaner",
    "imprimir": "impresora",
    "abrir": "carpeta-abierta",
    "herramientas": "cuadricula",
    "inicio": "casa",
}


class IconoDesconocido(KeyError):
    """El nombre pedido no está en el catálogo ni en los alias."""


def resolver(nombre: str) -> Icono:
    """Devuelve el Icono de `nombre`, siguiendo los alias.

    Lanza IconoDesconocido en vez de devolver algo vacío: un icono que
    falta es un error de programación, y es mejor verlo en los tests que
    descubrir un hueco en la UI en producción.
    """
    clave = ALIAS.get(nombre, nombre)
    try:
        return CATALOGO[clave]
    except KeyError:
        raise IconoDesconocido(
            f"No existe el icono {nombre!r}. Disponibles: "
            f"{', '.join(sorted(nombres()))}"
        ) from None


def nombres() -> set[str]:
    """Todos los nombres válidos, incluyendo alias."""
    return set(CATALOGO) | set(ALIAS)


def svg_documento(nombre: str, color: str = "#000000",
                  grosor: float | None = None) -> str:
    """Arma el SVG completo del icono con el color pedido.

    Es Python puro a propósito: se puede probar sin Qt y sirve para
    generar los assets del instalador o la documentación.
    """
    ico = resolver(nombre)
    ancho = grosor if grosor is not None else ico.grosor
    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEWBOX} {VIEWBOX}"'
        f' width="{VIEWBOX}" height="{VIEWBOX}">'
    ]
    if ico.relleno:
        for d in ico.trazos:
            partes.append(f'<path d="{d}" fill="{color}" stroke="none"/>')
    else:
        atributos = (
            f'fill="none" stroke="{color}" stroke-width="{ancho}"'
            ' stroke-linecap="round" stroke-linejoin="round"'
        )
        for d in ico.trazos:
            partes.append(f'<path d="{d}" {atributos}/>')
    for d in ico.puntos:
        partes.append(f'<path d="{d}" fill="{color}" stroke="none"/>')
    partes.append("</svg>")
    return "".join(partes)


# ═══════════════════════════════════════════════════════════════════════════════
#  Capa Qt — sólo si PyQt6 está instalado
# ═══════════════════════════════════════════════════════════════════════════════

try:
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap

    _QT = True
except ImportError:                                   # pragma: no cover
    _QT = False

try:
    from PyQt6.QtSvg import QSvgRenderer

    _SVG = _QT
except ImportError:                                   # pragma: no cover
    _SVG = False


#: Cache de pixmaps ya rasterizados: (nombre, px, color, grosor, dpr) → QPixmap.
#: Sin esto, cada repintado de una lista larga rasterizaría los mismos SVG
#: una y otra vez.
_cache: dict[tuple, object] = {}


def limpiar_cache() -> None:
    """Descarta los pixmaps cacheados (al cambiar de tema cambian los colores)."""
    _cache.clear()


def _color_hex(color: str | None) -> str:
    """Resuelve un color: un token del tema ('primary') o un color literal."""
    from modules.theme import THEME

    if not color:
        return THEME.get("text", "#000000")
    return THEME.get(color, color)


def _dpr() -> float:
    """Factor de densidad de la pantalla, para rasterizar sin pixelar."""
    if not _QT:                                       # pragma: no cover
        return 1.0
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            return max(1.0, float(app.devicePixelRatio()))
    except Exception:                                 # pragma: no cover
        pass
    return 1.0


def _dibujar_reserva(pm, color: str, px: int) -> None:            # pragma: no cover
    """Plan B si QtSvg no está: un cuadrado redondeado del color del icono.

    No es bonito, pero es visible y no rompe el layout. Sólo debería
    ocurrir en un build al que le falte el módulo QtSvg.
    """
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QColor(color))
    margen = px * 0.18
    painter.drawRoundedRect(
        QRectF(margen, margen, px - 2 * margen, px - 2 * margen),
        px * 0.15, px * 0.15,
    )
    painter.end()


def pixmap(nombre: str, tamano: int = 18, *, color: str | None = None,
           grosor: float | None = None):
    """QPixmap del icono, ya escalado al DPI de la pantalla.

    color: token del tema ('primary', 'danger', 'text_muted'…) o un color
           literal ('#ff0000'). Si se omite, usa el color de texto activo.
    """
    if not _QT:                                       # pragma: no cover
        raise RuntimeError("modules.iconos necesita PyQt6 para rasterizar")

    hexa = _color_hex(color)
    dpr = _dpr()
    clave = (nombre, tamano, hexa, grosor, dpr)
    cacheado = _cache.get(clave)
    if cacheado is not None:
        return cacheado

    px = max(1, int(round(tamano * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)

    if _SVG:
        renderer = QSvgRenderer(
            svg_documento(nombre, hexa, grosor).encode("utf-8"))
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, px, px))
        painter.end()
    else:                                             # pragma: no cover
        resolver(nombre)          # valida el nombre igual que la rama normal
        _dibujar_reserva(pm, hexa, px)

    pm.setDevicePixelRatio(dpr)
    _cache[clave] = pm
    return pm


def icono(nombre: str, tamano: int = 18, *, color: str | None = None,
          grosor: float | None = None):
    """QIcon del icono pedido."""
    return QIcon(pixmap(nombre, tamano, color=color, grosor=grosor))


def icono_app(tamano: int = 256):
    """Icono de la aplicación, dibujado (no leído de disco).

    Se usa como respaldo cuando no se encuentra assets/icon.ico, para que
    la ventana nunca quede con el icono genérico de Qt.
    """
    from modules.theme import THEME

    dpr = _dpr()
    px = max(1, int(round(tamano * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(THEME.get("primary", "#006b71")))
    painter.drawRoundedRect(QRectF(0, 0, px, px), px * 0.22, px * 0.22)
    painter.end()

    if _SVG:
        renderer = QSvgRenderer(
            svg_documento("firma", THEME.get("on_primary", "#ffffff"), 2.0)
            .encode("utf-8"))
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        margen = px * 0.2
        renderer.render(painter, QRectF(margen, margen,
                                        px - 2 * margen, px - 2 * margen))
        painter.end()

    pm.setDevicePixelRatio(dpr)
    return pm


def conectar_tema() -> None:
    """Vacía el cache cada vez que cambia el tema.

    La llama modules.theme al aplicar un tema; no hace falta invocarla a
    mano desde las pantallas.
    """
    if not _QT:                                       # pragma: no cover
        return
    from modules.theme import theme_signals

    theme_signals.changed.connect(lambda _modo: limpiar_cache())
