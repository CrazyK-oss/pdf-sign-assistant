"""
tests/test_iconos.py
============================================================
Tests del catálogo de iconos.

Por qué hacen falta
-------------------
Los iconos son trazos SVG escritos a mano dentro de un archivo Python.
Eso trae dos formas de romperlos que no dan ningún error visible:

  1. Un trazo mal formado. Qt no lanza excepción: dibuja lo que pudo
     interpretar, escupe "Invalid path data" por stderr —donde nadie
     mira— y sigue. Pasó de verdad con el icono de la bombilla, que se
     renderizaba a medias.
  2. Un nombre mal escrito en la UI (icono="carpta"). Se descubre al
     abrir esa pantalla, quizás semanas después.

Los tests de acá abajo cierran las dos puertas. La parte de catálogo es
Python puro y corre en el CI liviano; el render necesita PyQt6 y se
saltea solo si no está.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from modules.iconos import (
    ALIAS,
    CATALOGO,
    VIEWBOX,
    IconoDesconocido,
    nombres,
    resolver,
    svg_documento,
)

RAIZ = Path(__file__).resolve().parent.parent


# ── Salud del catálogo ────────────────────────────────────────────────────────

def test_el_catalogo_no_esta_vacio():
    assert len(CATALOGO) >= 40, "se esperaba un juego de iconos completo"


@pytest.mark.parametrize("nombre", sorted(CATALOGO))
def test_cada_icono_tiene_al_menos_un_trazo(nombre):
    ico = CATALOGO[nombre]
    assert ico.trazos, f"{nombre} no dibuja nada"
    assert ico.grosor > 0


@pytest.mark.parametrize("nombre", sorted(CATALOGO))
def test_los_nombres_son_kebab_case(nombre):
    """Un nombre con mayúsculas o guión bajo rompe la convención y hace
    que uno no adivine cómo se llama el icono que busca."""
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", nombre), nombre


@pytest.mark.parametrize("nombre", sorted(CATALOGO))
def test_los_trazos_empiezan_con_moveto(nombre):
    """Un trazo SVG que no arranca con M/m no tiene punto de partida:
    Qt lo descarta en silencio."""
    for i, d in enumerate(CATALOGO[nombre].trazos):
        assert d.lstrip()[:1] in "Mm", f"{nombre}[{i}] no empieza con M"


@pytest.mark.parametrize("nombre", sorted(CATALOGO))
def test_los_trazos_solo_usan_comandos_svg_validos(nombre):
    permitidos = set("MmLlHhVvCcSsQqTtAaZz0123456789.,-+eE \n\t")
    for i, d in enumerate(CATALOGO[nombre].trazos):
        sobrantes = set(d) - permitidos
        assert not sobrantes, f"{nombre}[{i}] tiene caracteres raros: {sobrantes}"


def test_los_alias_apuntan_a_iconos_que_existen():
    huerfanos = {a: destino for a, destino in ALIAS.items()
                 if destino not in CATALOGO}
    assert not huerfanos, f"alias rotos: {huerfanos}"


def test_ningun_alias_pisa_un_icono_real():
    """Si un alias se llamara igual que una entrada del catálogo, resolver()
    devolvería el alias y el icono real quedaría inalcanzable."""
    colisiones = set(ALIAS) & set(CATALOGO)
    assert not colisiones, f"alias que tapan un icono: {colisiones}"


def test_resolver_sigue_los_alias():
    assert resolver("editar") is CATALOGO["lapiz"]
    assert resolver("lapiz") is CATALOGO["lapiz"]


def test_resolver_avisa_cuando_el_nombre_no_existe():
    with pytest.raises(IconoDesconocido) as exc:
        resolver("no-existe-este-icono")
    # El mensaje lista los disponibles: es lo que salva al que se equivocó
    assert "carpeta" in str(exc.value)


# ── Generación del SVG ────────────────────────────────────────────────────────

def test_el_svg_lleva_el_color_pedido():
    svg = svg_documento("carpeta", "#ff0000")
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert 'stroke="#ff0000"' in svg
    assert f'viewBox="0 0 {VIEWBOX} {VIEWBOX}"' in svg


def test_los_iconos_rellenos_usan_fill_y_no_stroke():
    svg = svg_documento("chispa", "#00ff00")
    assert 'fill="#00ff00"' in svg
    assert "stroke-width" not in svg


def test_se_puede_forzar_el_grosor():
    assert 'stroke-width="3.5"' in svg_documento("carpeta", "#000", grosor=3.5)


@pytest.mark.parametrize("nombre", sorted(nombres()))
def test_todos_los_nombres_generan_svg(nombre):
    svg = svg_documento(nombre, "#123456")
    assert svg.count("<path") == len(resolver(nombre).trazos)


# ── Los nombres que usa la aplicación ─────────────────────────────────────────

#: Formas en que el código pide un icono. El nombre siempre es el primer
#: literal entre comillas después de la llamada o del `=`.
#:
#: El (?<!\w) del principio no es decorativo: sin él, la propiedad QSS
#: `soloicono="true"` del tema entraba como si fuera un icono llamado
#: "true".
_PEDIDOS = re.compile(
    r"""(?<![A-Za-z0-9_])
        (?:
          icono \s* = \s*
        | icono_nombre \s* = \s*
        | boton_icono \s* \( \s*
        | icono_label \s* \( \s*
        | IconoLabel \s* \( \s*
        | set_icono \s* \( \s*
        | set_nombre_icono \s* \( \s*
        | iconos\.pixmap \s* \( \s*
        | iconos\.icono \s* \( \s*
        )
        ["']([^"']*)["']
    """,
    re.VERBOSE,
)


def _fuentes():
    for ruta in sorted(RAIZ.rglob("*.py")):
        if any(p in ruta.parts for p in ("build", "dist", ".git",
                                         "__pycache__", "tests")):
            continue
        yield ruta


def test_todos_los_iconos_que_pide_la_ui_existen():
    """Atrapa los nombres mal escritos sin tener que abrir cada pantalla.

    Es el test más útil del archivo: un icono inexistente sólo se nota
    cuando alguien navega hasta esa pantalla, y para entonces ya está
    publicado.
    """
    validos = nombres()
    faltantes: list[str] = []

    for ruta in _fuentes():
        texto = ruta.read_text(encoding="utf-8")
        for m in _PEDIDOS.finditer(texto):
            nombre = m.group(1)
            if not nombre:
                continue            # icono="" = botón sin icono, es válido
            if nombre not in validos:
                linea = texto[:m.start()].count("\n") + 1
                faltantes.append(
                    f"{ruta.relative_to(RAIZ)}:{linea} → {nombre!r}")

    assert not faltantes, (
        "Hay iconos que la UI pide y el catálogo no tiene:\n  "
        + "\n  ".join(faltantes))


def test_la_ui_realmente_usa_iconos():
    """Salvaguarda del test anterior: si la expresión regular dejara de
    encontrar nada, pasaría en verde sin comprobar absolutamente nada."""
    total = sum(len(_PEDIDOS.findall(r.read_text(encoding="utf-8")))
                for r in _fuentes())
    assert total > 40, f"sólo se detectaron {total} usos de iconos"


# ── Render con Qt ─────────────────────────────────────────────────────────────

@pytest.mark.integracion
def test_qt_dibuja_todos_los_iconos_sin_quejarse():
    """Que ningún trazo produzca 'Invalid path data'.

    QSvgRenderer no lanza excepción con un trazo roto: lo dibuja a medias
    y avisa por el handler de mensajes de Qt. Hay que interceptarlo para
    enterarse.
    """
    pytest.importorskip("PyQt6", reason="Necesita las dependencias de la app")
    pytest.importorskip("PyQt6.QtSvg", reason="Necesita QtSvg")

    from PyQt6.QtCore import qInstallMessageHandler
    from PyQt6.QtSvg import QSvgRenderer

    quejas: list[str] = []
    actual = {"nombre": ""}

    def handler(_tipo, _ctx, mensaje):
        if "path" in mensaje.lower():
            quejas.append(f"{actual['nombre']}: {mensaje}")

    anterior = qInstallMessageHandler(handler)
    try:
        for nombre in sorted(CATALOGO):
            actual["nombre"] = nombre
            renderer = QSvgRenderer(
                svg_documento(nombre, "#000000").encode("utf-8"))
            assert renderer.isValid(), f"{nombre} no produjo un SVG válido"
    finally:
        qInstallMessageHandler(anterior)

    assert not quejas, "Qt rechazó estos trazos:\n  " + "\n  ".join(quejas)


@pytest.mark.integracion
def test_los_tonos_del_kit_usan_iconos_que_existen():
    """ui.TONOS mapea tono → (icono, color); un nombre mal escrito ahí
    haría explotar cualquier Chip o Aviso de ese tono."""
    pytest.importorskip("PyQt6", reason="Necesita las dependencias de la app")
    from modules.ui import TONOS

    for tono, (icono, _color) in TONOS.items():
        assert icono in nombres(), f"el tono {tono!r} pide el icono {icono!r}"


@pytest.mark.integracion
def test_el_pixmap_sale_con_el_tamano_pedido_y_no_vacio(qapp):
    # La QApplication viene del fixture de conftest y no de una variable
    # local: si este test creara la suya, al terminar Python la recolectaría
    # y Qt se llevaría puesto modules.theme.theme_signals, rompiendo los
    # módulos que corren después.
    from modules import iconos
    from modules.theme import apply_theme

    app = qapp
    apply_theme(app, "light")

    pm = iconos.pixmap("carpeta", 32, color="primary")
    assert not pm.isNull()
    assert pm.width() >= 32 and pm.height() >= 32

    # El cache tiene que devolver el mismo objeto para la misma clave
    assert iconos.pixmap("carpeta", 32, color="primary") is pm

    # …y soltarlo al cambiar de tema, porque el color va quemado adentro
    apply_theme(app, "dark")
    assert iconos.pixmap("carpeta", 32, color="primary") is not pm
