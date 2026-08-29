"""
tests/test_tema.py
============================================================
Tests de la hoja de estilos.

Qué protegen
------------
El QSS se arma con una f-string gigante, y Qt no avisa cuando algo sale
mal: si la hoja no se puede parsear, imprime "Could not parse application
stylesheet" por stderr —que nadie mira— y la aplicación arranca **sin
ningún estilo**. Pantalla gris de Qt crudo, con todo funcionando. Es de
los defectos más visibles que existen y el proceso ni se inmuta.

Pasó de verdad al agregar la flecha del desplegable: un `{{` de más en un
trozo que se insertaba como valor, y la hoja entera dejó de aplicarse.

Necesitan PyQt6.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt6", reason="Necesita las dependencias de la app")

from modules.theme import (  # noqa: E402
    DARK,
    LIGHT,
    _archivo_flecha,
    _build_stylesheet,
    apply_theme,
)


@pytest.fixture(scope="module")
def app(qapp):
    return qapp


@pytest.mark.parametrize("paleta", [LIGHT, DARK], ids=["light", "dark"])
def test_la_hoja_no_deja_llaves_sin_resolver(paleta):
    """Una llave doble sobrante es exactamente lo que rompió la hoja: la
    parte que se inserta como valor no se vuelve a interpretar, así que
    sus `{{` llegan literales al CSS y Qt descarta TODO el stylesheet."""
    qss = _build_stylesheet(paleta, "/tmp/flecha.png")
    assert "{{" not in qss, "quedaron llaves dobles sin resolver"
    assert "}}" not in qss


@pytest.mark.parametrize("paleta", [LIGHT, DARK], ids=["light", "dark"])
def test_las_llaves_de_la_hoja_estan_balanceadas(paleta):
    qss = _build_stylesheet(paleta, "/tmp/flecha.png")
    assert qss.count("{") == qss.count("}")


def test_la_hoja_se_aplica_de_verdad(app):
    """Que Qt la acepte, no sólo que se genere. Con la hoja rota, Qt la
    descarta en silencio y `styleSheet()` queda con el texto pero la app
    sin estilo — así que se compara contra lo que Qt devuelve."""
    apply_theme(app, "light")
    aplicada = app.styleSheet()
    assert aplicada, "la app quedó sin hoja de estilos"
    assert "QMainWindow" in aplicada


# ── La flecha del desplegable ────────────────────────────────────────────────

def test_se_genera_el_archivo_de_la_flecha(app):
    """`image: url(...)` sólo acepta un archivo, y los iconos de esta app
    se dibujan en memoria desde SVG: hay que escribir uno."""
    apply_theme(app, "light")
    ruta = _archivo_flecha(LIGHT, "light")
    assert ruta, "no se generó la flecha"
    assert Path(ruta).is_file()
    assert Path(ruta).stat().st_size > 0


def test_la_flecha_entra_en_la_hoja(app):
    """Sin imagen, Qt no dibuja NADA en el desplegable: en cuanto una hoja
    de estilo toca ::drop-down se pierde el control nativo, y el combo
    queda indistinguible de un campo de texto."""
    apply_theme(app, "light")
    qss = app.styleSheet()
    assert "QComboBox::down-arrow" in qss
    assert "image: url(" in qss


def test_cada_tema_tiene_su_flecha(app):
    """El color va quemado en el PNG: compartir archivo entre temas dejaría
    la flecha del tema anterior."""
    clara = _archivo_flecha(LIGHT, "light")
    oscura = _archivo_flecha(DARK, "dark")
    assert clara != oscura
    assert Path(clara).read_bytes() != Path(oscura).read_bytes()


def test_sin_flecha_la_regla_se_omite_entera():
    """Si el archivo no se pudo escribir, mejor omitir la regla que dejar
    un `url()` vacío: sin la regla vuelve el dibujo por defecto de Qt."""
    qss = _build_stylesheet(LIGHT, "")
    assert "QComboBox::down-arrow" not in qss
    assert "{{" not in qss


def test_la_ruta_de_la_flecha_usa_barras_normales(app):
    """QSS quiere barras normales incluso en Windows; con las invertidas,
    `url()` no resuelve y la flecha no aparece."""
    ruta = _archivo_flecha(LIGHT, "light")
    assert "\\" not in ruta


def test_alternar_el_tema_no_rompe_la_hoja(app):
    """El cambio de tema regenera la flecha y rearma el QSS entero."""
    for modo in ("dark", "light", "dark", "light"):
        apply_theme(app, modo)
        assert app.styleSheet()
        assert "{{" not in app.styleSheet()
