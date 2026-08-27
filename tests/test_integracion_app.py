"""
tests/test_integracion_app.py
============================================================
Smoke test de la ventana principal y el menú de herramientas.

Qué protege
-----------
El menú se arma solo a partir de `navegacion.CATALOGO`, pero cada
herramienta necesita además que alguien registre su widget en la ventana.
Es fácil sumar una entrada al catálogo y olvidarse de la segunda mitad: la
tarjeta aparece en el inicio, el usuario le hace clic y no pasa nada.

Estos tests abren la ventana de verdad y navegan a **todas** las
herramientas del catálogo, así que ese olvido falla acá y no en la
máquina del usuario.

Ojo: crear la ventana ejecuta `setup_directories()`, que es lo que hace la
app al arrancar. En una máquina de desarrollo eso crea las carpetas de
datos y documentos, igual que si se hubiera abierto la aplicación.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6", reason="Necesita las dependencias de la app")
pytest.importorskip("pymupdf", reason="Necesita PyMuPDF")

pytestmark = pytest.mark.integracion


@pytest.fixture(scope="module")
def app(qapp):
    """La QApplication compartida (ver tests/conftest.py)."""
    return qapp


@pytest.fixture(scope="module")
def ventana(app):
    from modules.theme import apply_theme

    apply_theme(app, "light")

    import main

    v = main.VentanaPrincipal()
    v.resize(1100, 720)
    # show() hace falta de verdad: sin mostrarla, Qt no entrega el
    # QResizeEvent y el colapso de la barra lateral nunca se dispara.
    # Con QT_QPA_PLATFORM=offscreen no aparece ninguna ventana.
    v.show()
    app.processEvents()
    yield v
    v.close()


# ── Navegación ────────────────────────────────────────────────────────────────

def test_todas_las_herramientas_del_catalogo_se_pueden_abrir(app, ventana):
    """Si alguien suma una herramienta al catálogo y no registra su widget,
    la tarjeta queda muerta. Acá se nota."""
    from modules.navegacion import CATALOGO, INICIO

    for destino in (INICIO, *(h.id for h in CATALOGO)):
        ventana._ir_a(destino)
        app.processEvents()
        actual = ventana.paginas.currentWidget()
        assert actual is not None, f"{destino} no tiene pantalla"
        assert actual is ventana._paginas[destino]


def test_la_barra_lateral_marca_la_herramienta_abierta(app, ventana):
    from modules.navegacion import CATALOGO, INICIO

    for destino in (INICIO, *(h.id for h in CATALOGO)):
        ventana._ir_a(destino)
        app.processEvents()
        marcados = [clave for clave, b in ventana.barra_lateral._botones.items()
                    if b.isChecked()]
        assert marcados == [destino]


def test_las_tarjetas_del_inicio_navegan(app, ventana):
    """La tarjeta del launcher tiene que llevar a la misma pantalla que el
    botón de la barra lateral."""
    from modules.navegacion import CATALOGO

    ventana._ir_a("inicio")
    app.processEvents()

    for tarjeta, herramienta in zip(ventana.pantalla_inicio._tarjetas, CATALOGO):
        tarjeta.activada.emit()
        app.processEvents()
        assert ventana.paginas.currentWidget() is ventana._paginas[herramienta.id]
        ventana._ir_a("inicio")
        app.processEvents()


def test_la_herramienta_de_escaneo_se_crea_recien_al_abrirla(app):
    """Consulta el escáner al construirse: hacerlo en el arranque
    retrasaría la ventana por algo que quizás nunca se use."""
    from modules.theme import apply_theme

    apply_theme(app, "light")
    import main

    v = main.VentanaPrincipal()
    try:
        assert "escanear" not in v._paginas
        v._ir_a("escanear")
        app.processEvents()
        assert "escanear" in v._paginas
        assert v._herramienta_escaneo is not None
    finally:
        v.close()


# ── Responsive ────────────────────────────────────────────────────────────────

def test_la_barra_lateral_se_colapsa_en_ventanas_angostas(app, ventana):
    from modules.theme import BREAKPOINT, SIZE

    ventana.resize(1100, 720)
    app.processEvents()
    assert not ventana.barra_lateral.compacta
    assert ventana.barra_lateral.width() == SIZE["sidebar"]

    ventana.resize(BREAKPOINT["md"] - 120, 720)
    app.processEvents()
    assert ventana.barra_lateral.compacta
    assert ventana.barra_lateral.width() == SIZE["rail"]
    # Colapsada, los botones quedan sin texto pero conservan el tooltip
    assert ventana.barra_lateral.btn_ajustes.text() == ""
    assert ventana.barra_lateral.btn_ajustes.toolTip()

    ventana.resize(1100, 720)
    app.processEvents()
    assert not ventana.barra_lateral.compacta
    assert ventana.barra_lateral.btn_ajustes.text().strip() == "Ajustes"


# ── Tema ──────────────────────────────────────────────────────────────────────

def test_alternar_el_tema_repinta_los_iconos(app, ventana):
    """Los iconos llevan el color quemado adentro: si el cache no se tira
    al cambiar de tema, quedan del color anterior."""
    from modules import iconos
    from modules.theme import current_mode

    ventana._ir_a("inicio")
    app.processEvents()

    antes = iconos.pixmap("carpeta", 18, color="text")
    modo_inicial = current_mode()

    ventana._toggle_tema()
    app.processEvents()

    assert current_mode() != modo_inicial
    assert iconos.pixmap("carpeta", 18, color="text") is not antes

    ventana._toggle_tema()          # dejarlo como estaba
    app.processEvents()
    assert current_mode() == modo_inicial


def test_el_boton_de_tema_anuncia_a_donde_lleva(app, ventana):
    from modules.theme import is_dark

    for _ in range(2):
        esperado = "Tema claro" if is_dark() else "Tema oscuro"
        assert ventana.barra_lateral.btn_tema.text().strip() == esperado
        ventana._toggle_tema()
        app.processEvents()
