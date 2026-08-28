"""
tests/test_previa.py
============================================================
Tests del módulo que dibuja una página al tamaño en que se la ve.

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

3. **Dibujar la página equivocada de un PDF.** Todas las páginas de un
   archivo comparten la ruta: si el índice no entrara en la clave del
   cache, un documento de 40 páginas se vería como 40 copias de la
   primera. Se ve enseguida, pero sólo si alguien mira.

Necesitan PyQt6, así que llevan la marca `integracion`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt6", reason="Necesita las dependencias de la app")
pytest.importorskip("PIL", reason="Necesita Pillow")

from PIL import Image  # noqa: E402

import modules.previa as pv  # noqa: E402
from modules.documento import Documento  # noqa: E402

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


def pag(ruta, rotacion=0, *, origen=None, indice=0):
    """Una página suelta para pasarle al renderizador.

    El módulo dibuja páginas, no rutas: el origen decide si hay que
    decodificar una imagen o rasterizar una página de PDF.
    """
    from modules.documento import ORIGEN_ESCANER, ORIGEN_PDF

    if origen is None:
        origen = ORIGEN_PDF if str(ruta).lower().endswith(".pdf") else ORIGEN_ESCANER
    return Documento().agregar(ruta, rotacion=rotacion, origen=origen,
                               indice_pagina=indice)


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
    assert pv.cuantizar(pedido) == esperado


def test_cuantizar_evita_que_el_cache_sea_inutil(app, hoja, etiqueta):
    """Arrastrar el borde de la ventana no debe generar una entrada de
    cache por cada píxel de ancho."""
    pv.limpiar_cache()
    for alto in range(500, 560):          # 60 tamaños distintos
        etiqueta.resize(400, alto)
        pv.escalar_para(etiqueta, pag(hoja))
    assert len(pv._CACHE) <= 3, (
        f"60 tamaños seguidos generaron {len(pv._CACHE)} entradas de cache")


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
    pv.limpiar_cache()
    etiqueta.resize(ancho, alto)
    mostrado = pv.escalar_para(etiqueta, pag(hoja))
    assert not mostrado.isNull()

    lado = min(pv.cuantizar(max(ancho, alto)), pv.LADO_PREVIA_MAX)
    fuente = pv.render(pag(hoja), lado)

    assert mostrado.height() <= fuente.height(), (
        f"con un panel de {ancho}x{alto} la imagen se agranda "
        f"{mostrado.height() / fuente.height():.2f}×")
    assert mostrado.width() <= fuente.width()


def test_la_previa_llena_el_panel(app, hoja, etiqueta):
    """No alcanza con no agrandar: tiene que aprovechar el espacio."""
    etiqueta.resize(708, 786)
    mostrado = pv.escalar_para(etiqueta, pag(hoja))
    # A4 es más alto que ancho, así que el alto es el que manda
    assert mostrado.height() == 786
    assert 0 < mostrado.width() <= 708


def test_una_imagen_mas_chica_que_el_panel_no_se_infla_al_leer(app, tmp_path,
                                                              etiqueta):
    """Con una foto chiquita no hay nada que ganar: se lee tal cual."""
    chica = tmp_path / "chica.png"
    Image.new("RGB", (200, 260), (10, 20, 30)).save(chica)

    pv.limpiar_cache()
    etiqueta.resize(800, 900)
    fuente = pv.render(pag(chica), 1024)
    assert (fuente.width(), fuente.height()) == (200, 260), (
        "render no debe agrandar el archivo original")


def test_la_miniatura_tampoco_agranda(app, hoja, etiqueta):
    etiqueta.resize(72, pv.LADO_MINIATURA)
    mostrado = pv.escalar_para(etiqueta, pag(hoja), tope=pv.LADO_MINIATURA * 4)
    assert mostrado.height() <= pv.LADO_MINIATURA
    assert not mostrado.isNull()


def test_el_tope_acota_el_trabajo_en_monitores_enormes(app, hoja, etiqueta):
    """Un panel gigante no debe hacer que se decodifique la imagen entera."""
    etiqueta.resize(4000, 5000)
    pv.limpiar_cache()
    pv.escalar_para(etiqueta, pag(hoja))
    leido = max(pm.width() for pm in pv._CACHE.values())
    alto_leido = max(pm.height() for pm in pv._CACHE.values())
    assert max(leido, alto_leido) <= pv.LADO_PREVIA_MAX


# ── Rotación ──────────────────────────────────────────────────────────────────

def test_la_rotacion_cambia_la_orientacion_del_pixmap(app, hoja, etiqueta):
    etiqueta.resize(700, 700)
    vertical = pv.escalar_para(etiqueta, pag(hoja, 0))
    girada = pv.escalar_para(etiqueta, pag(hoja, 90))
    assert vertical.height() > vertical.width()
    assert girada.width() > girada.height(), "girar 90° debe dejarla apaisada"


def test_cada_rotacion_tiene_su_entrada_de_cache(app, hoja, etiqueta):
    pv.limpiar_cache()
    etiqueta.resize(400, 500)
    pv.escalar_para(etiqueta, pag(hoja, 0))
    entradas = len(pv._CACHE)
    pv.escalar_para(etiqueta, pag(hoja, 90))
    assert len(pv._CACHE) == entradas + 1


# ── Presupuesto de memoria ────────────────────────────────────────────────────

def test_el_cache_respeta_su_presupuesto_de_bytes(app, tmp_path, etiqueta):
    """Antes el tope era por cantidad de entradas: 160 pixmaps de vista
    previa se iban muy por encima del gigabyte."""
    pv.limpiar_cache()
    etiqueta.resize(900, 1100)

    # Fuentes de 150 DPI: alcanzan para llenar el panel de 900x1100 y se
    # decodifican cuatro veces más rápido que un A4 de 300.
    for i in range(40):
        ruta = tmp_path / f"p{i:02d}.png"
        Image.new("RGB", (1240, 1754), (240, 240 - i, 240)).save(ruta)
        pv.escalar_para(etiqueta, pag(ruta))

    assert pv.bytes_en_cache() <= pv.CACHE_BYTES_MAX, (
        f"el cache llegó a {pv.bytes_en_cache() / 1e6:.0f} MB, por encima del "
        f"tope de {pv.CACHE_BYTES_MAX / 1e6:.0f} MB")
    assert pv.bytes_en_cache() > 0, "no debería haber quedado vacío"


def test_limpiar_cache_deja_la_cuenta_en_cero(app, hoja, etiqueta):
    etiqueta.resize(400, 500)
    pv.escalar_para(etiqueta, pag(hoja))
    assert pv.bytes_en_cache() > 0
    pv.limpiar_cache()
    assert pv.bytes_en_cache() == 0 and not pv._CACHE


def test_una_imagen_ilegible_no_rompe_ni_ensucia_el_cache(app, tmp_path,
                                                          etiqueta):
    roto = tmp_path / "roto.png"
    roto.write_bytes(b"esto no es un PNG")
    pv.limpiar_cache()
    etiqueta.resize(400, 500)
    assert pv.escalar_para(etiqueta, pag(roto)).isNull()
    assert pv.bytes_en_cache() == 0


def test_un_archivo_que_no_existe_devuelve_pixmap_vacio(app, tmp_path,
                                                        etiqueta):
    etiqueta.resize(400, 500)
    assert pv.escalar_para(etiqueta, pag(tmp_path / 'fantasma.png')).isNull()


# ── Páginas de PDF ────────────────────────────────────────────────────────────

pymupdf = pytest.importorskip("pymupdf", reason="Necesita PyMuPDF")


@pytest.fixture(scope="module")
def folleto(tmp_path_factory) -> Path:
    """Un PDF de 3 páginas, cada una de un color distinto y bien plano.

    Colores planos porque lo que se comprueba es *qué* página se dibujó, y
    mirar el color dominante es la forma más directa de saberlo.
    """
    ruta = tmp_path_factory.mktemp("previa_pdf") / "folleto.pdf"
    doc = pymupdf.open()
    for color in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
        pagina = doc.new_page(width=595, height=842)      # A4 en puntos
        pagina.draw_rect(pagina.rect, color=color, fill=color)
    doc.save(ruta)
    doc.close()
    return ruta


def canal_dominante(pm) -> int:
    """0=rojo, 1=verde, 2=azul: qué canal manda en el centro del pixmap."""
    img = pm.toImage()
    color = img.pixelColor(img.width() // 2, img.height() // 2)
    return max(range(3), key=lambda i: (color.red(), color.green(),
                                        color.blue())[i])


def test_se_dibuja_la_pagina_pedida_y_no_siempre_la_primera(app, folleto,
                                                            etiqueta):
    """El error que este archivo vigila: todas las páginas de un PDF
    comparten la ruta. Si el índice no entrara en la clave del cache, un
    documento de 40 páginas se vería como 40 copias de la primera."""
    pv.limpiar_cache()
    etiqueta.resize(300, 400)

    canales = [canal_dominante(pv.escalar_para(etiqueta, pag(folleto, indice=i)))
               for i in range(3)]
    assert canales == [0, 1, 2], (
        f"se esperaban rojo, verde y azul y salió {canales}")


def test_cada_pagina_tiene_su_entrada_de_cache(app, folleto, etiqueta):
    pv.limpiar_cache()
    etiqueta.resize(300, 400)
    for i in range(3):
        pv.escalar_para(etiqueta, pag(folleto, indice=i))
    assert len(pv._CACHE) == 3


def test_una_pagina_de_pdf_se_dibuja(app, folleto, etiqueta):
    etiqueta.resize(400, 560)
    pm = pv.escalar_para(etiqueta, pag(folleto))
    assert not pm.isNull()
    assert pm.height() == 560, "tiene que llenar el panel"


def test_la_pagina_de_pdf_conserva_la_proporcion(app, folleto, etiqueta):
    """A4 es 1:√2. Si la proporción se perdiera, el texto saldría estirado."""
    etiqueta.resize(600, 600)
    pm = pv.escalar_para(etiqueta, pag(folleto))
    proporcion = pm.height() / pm.width()
    assert abs(proporcion - 842 / 595) < 0.02, proporcion


def test_girar_una_pagina_de_pdf_la_deja_apaisada(app, folleto, etiqueta):
    etiqueta.resize(700, 700)
    vertical = pv.escalar_para(etiqueta, pag(folleto))
    girada = pv.escalar_para(etiqueta, pag(folleto, 90))
    assert vertical.height() > vertical.width()
    assert girada.width() > girada.height()


def test_una_pagina_de_pdf_si_puede_agrandarse(app, folleto, etiqueta):
    """A diferencia de una imagen, una página de PDF es vectorial: pedirla
    más grande la rasteriza más grande, no la infla. Es lo que uno quiere
    al mirar la previa de un texto chico."""
    etiqueta.resize(1000, 1400)
    pm = pv.escalar_para(etiqueta, pag(folleto))
    assert pm.height() == 1400


def test_la_pagina_de_pdf_respeta_el_tope(app, folleto, etiqueta):
    """Justamente porque puede agrandarse, hace falta un techo: en un
    monitor enorme no se va a rasterizar un póster."""
    pv.limpiar_cache()
    etiqueta.resize(4000, 5000)
    pv.escalar_para(etiqueta, pag(folleto))
    mayor = max(max(pm.width(), pm.height()) for pm in pv._CACHE.values())
    assert mayor <= pv.LADO_PREVIA_MAX


def test_una_pagina_que_no_existe_en_el_pdf_no_rompe(app, folleto, etiqueta):
    etiqueta.resize(300, 400)
    assert pv.escalar_para(etiqueta, pag(folleto, indice=99)).isNull()


def test_un_pdf_ilegible_no_rompe_ni_ensucia_el_cache(app, tmp_path, etiqueta):
    roto = tmp_path / "roto.pdf"
    roto.write_bytes(b"esto no es un PDF")
    pv.limpiar_cache()
    etiqueta.resize(300, 400)
    assert pv.escalar_para(etiqueta, pag(roto)).isNull()
    assert pv.bytes_en_cache() == 0


def test_dibujar_no_deja_el_pdf_abierto(app, folleto, etiqueta, tmp_path):
    """Se abre y se cierra en cada render a propósito: en Windows, tener el
    archivo abierto impide renombrar encima de él, y guardar el resultado
    sobre el PDF que se abrió es lo más común del mundo."""
    import os
    import shutil

    copia = tmp_path / "copia.pdf"
    shutil.copy(folleto, copia)

    etiqueta.resize(300, 400)
    assert not pv.escalar_para(etiqueta, pag(copia)).isNull()

    nuevo = tmp_path / "nuevo.pdf"
    shutil.copy(folleto, nuevo)
    os.replace(nuevo, copia)          # en Windows fallaría con el archivo abierto
    assert copia.is_file()


def test_dimensiones_de_una_pagina_de_pdf(app, folleto):
    assert pv.dimensiones(pag(folleto)) == (595, 842)


def test_dimensiones_de_una_imagen(app, hoja):
    assert pv.dimensiones(pag(hoja)) == A4_300DPI


def test_dimensiones_de_algo_ilegible(app, tmp_path):
    roto = tmp_path / "roto.pdf"
    roto.write_bytes(b"no soy un PDF")
    assert pv.dimensiones(pag(roto)) == (0, 0)


def test_miniatura_de_una_pagina_de_pdf(app, folleto):
    pm = pv.miniatura(pag(folleto, indice=1))
    assert not pm.isNull()
    assert max(pm.width(), pm.height()) <= pv.LADO_MINIATURA
    assert canal_dominante(pm) == 1, "la miniatura también debe ser la página 2"
