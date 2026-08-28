"""
tests/test_integracion_previa.py
============================================================
Tests del escalado de imágenes de la herramienta "Escanear a PDF".

Qué protege
-----------
Dos defectos que no rompen nada y por eso se notan tarde:

1. **Agrandar la imagen.** La vista previa se leía con un tope fijo de
   420 px y después se escalaba al panel; pero el panel crece con la
   ventana, así que en cuanto pasaba de 420 el resultado se agrandaba y
   se veía blando. Medido antes del arreglo: 1,14× en una ventana de
   1000 px de ancho y 2,63× en una de 2560. Nadie ve una excepción: sólo
   una imagen fea.

2. **Un cache sin techo real.** Estaba acotado por cantidad de entradas
   (160), un número pensado para miniaturas de medio mega. Con la previa
   pidiendo pixmaps de varios MB, esas mismas 160 entradas pasaban a ser
   más de un gigabyte.

Necesitan PyQt6, así que llevan la marca `integracion`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt6", reason="Necesita las dependencias de la app")
pytest.importorskip("PIL", reason="Necesita Pillow")

from PIL import Image  # noqa: E402

import modules.herramienta_escaneo as he  # noqa: E402

pytestmark = pytest.mark.integracion

#: Un A4 escaneado a 300 DPI, que es lo que entrega la herramienta.
A4_300DPI = (2480, 3508)


@pytest.fixture(scope="module")
def app(qapp):
    """La QApplication compartida (ver tests/conftest.py)."""
    from modules.theme import apply_theme

    apply_theme(qapp, "light")
    return qapp


@pytest.fixture(scope="module")
def hoja(tmp_path_factory) -> Path:
    """Se escribe una sola vez: un A4 a 300 DPI son 8,7 millones de píxeles
    y generarlo por test hacía que este archivo tardara más que el resto de
    la suite junto."""
    ruta = tmp_path_factory.mktemp("previa") / "hoja.png"
    Image.new("RGB", A4_300DPI, (250, 250, 248)).save(ruta, dpi=(300, 300))
    return ruta


@pytest.fixture
def etiqueta(app):
    """Un QLabel suelto al que fijarle el tamaño que se quiera probar."""
    from PyQt6.QtWidgets import QLabel

    lbl = QLabel()
    yield lbl
    lbl.deleteLater()


# ── Cuantización de tamaños ───────────────────────────────────────────────────

@pytest.mark.parametrize("pedido, esperado", [
    (1, 128), (128, 128), (129, 256), (420, 512), (512, 512), (513, 640),
])
def test_cuantizar_redondea_hacia_arriba(pedido, esperado):
    assert he.cuantizar(pedido) == esperado


def test_cuantizar_evita_que_el_cache_sea_inutil(app, hoja, etiqueta):
    """Arrastrar el borde de la ventana no debe generar una entrada de
    cache por cada píxel de ancho."""
    he.limpiar_cache()
    for alto in range(500, 560):          # 60 tamaños distintos
        etiqueta.resize(400, alto)
        he.escalar_para(etiqueta, hoja)
    assert len(he._CACHE) <= 3, (
        f"60 tamaños seguidos generaron {len(he._CACHE)} entradas de cache")


# ── Lo importante: nunca agrandar ─────────────────────────────────────────────

@pytest.mark.parametrize("ancho, alto", [
    (300, 400),      # panel chico
    (420, 486),      # ventana de 1200 px
    (540, 656),      # ventana de 1500 px
    (708, 786),      # ventana de 1920 px
    (964, 1106),     # ventana de 2560 px
])
def test_la_previa_nunca_agranda_la_imagen(app, hoja, etiqueta, ancho, alto):
    """El pixmap mostrado no puede tener más píxeles que el que se leyó."""
    he.limpiar_cache()
    etiqueta.resize(ancho, alto)
    mostrado = he.escalar_para(etiqueta, hoja)
    assert not mostrado.isNull()

    lado = min(he.cuantizar(max(ancho, alto)), he.LADO_PREVIA_MAX)
    fuente = he.leer_escalada(hoja, lado)

    assert mostrado.height() <= fuente.height(), (
        f"con un panel de {ancho}x{alto} la imagen se agranda "
        f"{mostrado.height() / fuente.height():.2f}×")
    assert mostrado.width() <= fuente.width()


def test_la_previa_llena_el_panel(app, hoja, etiqueta):
    """No alcanza con no agrandar: tiene que aprovechar el espacio."""
    etiqueta.resize(708, 786)
    mostrado = he.escalar_para(etiqueta, hoja)
    # A4 es más alto que ancho, así que el alto es el que manda
    assert mostrado.height() == 786
    assert 0 < mostrado.width() <= 708


def test_una_imagen_mas_chica_que_el_panel_no_se_infla_al_leer(app, tmp_path,
                                                              etiqueta):
    """Con una foto chiquita no hay nada que ganar: se lee tal cual."""
    chica = tmp_path / "chica.png"
    Image.new("RGB", (200, 260), (10, 20, 30)).save(chica)

    he.limpiar_cache()
    etiqueta.resize(800, 900)
    fuente = he.leer_escalada(chica, 1024)
    assert (fuente.width(), fuente.height()) == (200, 260), (
        "leer_escalada no debe agrandar el archivo original")


def test_la_miniatura_tampoco_agranda(app, hoja, etiqueta):
    etiqueta.resize(72, he.LADO_MINIATURA)
    mostrado = he.escalar_para(etiqueta, hoja, tope=he.LADO_MINIATURA * 4)
    assert mostrado.height() <= he.LADO_MINIATURA
    assert not mostrado.isNull()


def test_el_tope_acota_el_trabajo_en_monitores_enormes(app, hoja, etiqueta):
    """Un panel gigante no debe hacer que se decodifique la imagen entera."""
    etiqueta.resize(4000, 5000)
    he.limpiar_cache()
    he.escalar_para(etiqueta, hoja)
    leido = max(pm.width() for pm in he._CACHE.values())
    alto_leido = max(pm.height() for pm in he._CACHE.values())
    assert max(leido, alto_leido) <= he.LADO_PREVIA_MAX


# ── Rotación ──────────────────────────────────────────────────────────────────

def test_la_rotacion_cambia_la_orientacion_del_pixmap(app, hoja, etiqueta):
    etiqueta.resize(700, 700)
    vertical = he.escalar_para(etiqueta, hoja, 0)
    girada = he.escalar_para(etiqueta, hoja, 90)
    assert vertical.height() > vertical.width()
    assert girada.width() > girada.height(), "girar 90° debe dejarla apaisada"


def test_cada_rotacion_tiene_su_entrada_de_cache(app, hoja, etiqueta):
    he.limpiar_cache()
    etiqueta.resize(400, 500)
    he.escalar_para(etiqueta, hoja, 0)
    entradas = len(he._CACHE)
    he.escalar_para(etiqueta, hoja, 90)
    assert len(he._CACHE) == entradas + 1


# ── Presupuesto de memoria ────────────────────────────────────────────────────

def test_el_cache_respeta_su_presupuesto_de_bytes(app, tmp_path, etiqueta):
    """Antes el tope era por cantidad de entradas: 160 pixmaps de vista
    previa se iban muy por encima del gigabyte."""
    he.limpiar_cache()
    etiqueta.resize(900, 1100)

    # Fuentes de 150 DPI: alcanzan para llenar el panel de 900x1100 y se
    # decodifican cuatro veces más rápido que un A4 de 300.
    for i in range(40):
        ruta = tmp_path / f"p{i:02d}.png"
        Image.new("RGB", (1240, 1754), (240, 240 - i, 240)).save(ruta)
        he.escalar_para(etiqueta, ruta)

    assert he._cache_bytes <= he._CACHE_BYTES_MAX, (
        f"el cache llegó a {he._cache_bytes / 1e6:.0f} MB, por encima del "
        f"tope de {he._CACHE_BYTES_MAX / 1e6:.0f} MB")
    assert he._cache_bytes > 0, "no debería haber quedado vacío"


def test_limpiar_cache_deja_la_cuenta_en_cero(app, hoja, etiqueta):
    etiqueta.resize(400, 500)
    he.escalar_para(etiqueta, hoja)
    assert he._cache_bytes > 0
    he.limpiar_cache()
    assert he._cache_bytes == 0 and not he._CACHE


def test_una_imagen_ilegible_no_rompe_ni_ensucia_el_cache(app, tmp_path,
                                                          etiqueta):
    roto = tmp_path / "roto.png"
    roto.write_bytes(b"esto no es un PNG")
    he.limpiar_cache()
    etiqueta.resize(400, 500)
    assert he.escalar_para(etiqueta, roto).isNull()
    assert he._cache_bytes == 0


def test_un_archivo_que_no_existe_devuelve_pixmap_vacio(app, tmp_path,
                                                        etiqueta):
    etiqueta.resize(400, 500)
    assert he.escalar_para(etiqueta, tmp_path / "fantasma.png").isNull()
