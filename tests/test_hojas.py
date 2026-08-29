"""
tests/test_hojas.py
============================================================
Tests de la detección de hojas en blanco y del intercalado de dos pasadas.

Las imágenes de prueba se generan imitando lo que devuelve un escáner de
verdad, no hojas blancas perfectas: papel gris claro, ruido de sensor y la
franja oscura que el alimentador deja en los bordes. Con blancos puros
estos tests pasarían siempre y no probarían nada — que es exactamente el
error que hace inútil a una detección de páginas vacías.

La regla que se defiende: ante la duda, la hoja NO está en blanco. Dejar
una página vacía de más es una molestia; borrar una con contenido es
perder trabajo del usuario.
"""

from __future__ import annotations

import random

import pytest

pytest.importorskip("PIL", reason="Necesita Pillow")

from PIL import Image, ImageDraw  # noqa: E402

from modules.hojas import (  # noqa: E402
    COBERTURA_VACIA,
    cobertura_de_tinta,
    descuadre,
    es_hoja_en_blanco,
    hojas_en_blanco,
    intercalar,
)

#: Tamaño de una hoja A4 a 150 dpi, que es la escala real de un escaneo.
A4 = (1240, 1754)


def hoja(ruta, *, texto_lineas=0, gris_papel=243, ruido=True,
         franja_borde=True, mancha=None, perforaciones=False,
         raya_vertical=False, ruido_sigma=None):
    """Una hoja como la devuelve un escáner.

    `texto_lineas` dibuja renglones de tinta; `franja_borde` agrega la
    sombra que deja el rodillo del alimentador, que es justo lo que hace
    fallar a una detección ingenua. `ruido_sigma` simula un sensor sucio
    con ruido gaussiano de verdad.
    """
    img = Image.new("L", A4, gris_papel)
    dib = ImageDraw.Draw(img)

    if ruido_sigma:
        # Semilla fija: un test que a veces pasa no sirve de nada.
        rnd = random.Random(7)
        px = img.load()
        for _ in range(200_000):
            x, y = rnd.randrange(A4[0]), rnd.randrange(A4[1])
            px[x, y] = max(0, min(255, int(rnd.gauss(gris_papel, ruido_sigma))))
    elif ruido:
        # Ruido determinista, sin random: un test que a veces pasa no sirve.
        for y in range(0, A4[1], 7):
            for x in range((y // 7) % 5, A4[0], 11):
                dib.point((x, y), fill=gris_papel - 18)

    if perforaciones:
        for y in (400, 870, 1340):
            dib.ellipse([40, y, 75, y + 35], fill=10)

    if raya_vertical:
        # Suciedad en el vidrio del alimentador: sale en todas las hojas.
        dib.rectangle([620, 0, 623, A4[1]], fill=40)

    if franja_borde:
        alto_franja = 14
        dib.rectangle([0, 0, A4[0], alto_franja], fill=60)
        dib.rectangle([0, A4[1] - alto_franja, A4[0], A4[1]], fill=60)

    for i in range(texto_lineas):
        y = 200 + i * 60
        dib.rectangle([150, y, A4[0] - 150, y + 18], fill=25)

    if mancha:
        x, y, lado = mancha
        dib.rectangle([x, y, x + lado, y + lado], fill=30)

    img.save(ruta)
    return ruta


@pytest.fixture
def vacia(tmp_path):
    """El dorso de una hoja impresa de un solo lado."""
    return hoja(tmp_path / "vacia.png")


@pytest.fixture
def con_texto(tmp_path):
    return hoja(tmp_path / "texto.png", texto_lineas=14)


# ═══════════════════════════════════════════════════════════════════════════════
#  Detección
# ═══════════════════════════════════════════════════════════════════════════════

def test_un_dorso_en_blanco_se_detecta(vacia):
    assert es_hoja_en_blanco(vacia)


def test_una_hoja_con_texto_no(con_texto):
    assert not es_hoja_en_blanco(con_texto)


def test_la_franja_del_alimentador_no_cuenta_como_contenido(tmp_path):
    """El borde oscuro que deja el rodillo aparece en TODAS las hojas del
    alimentador. Sin recortar los bordes antes de medir, ninguna hoja
    vacía se detectaría nunca y la función sería decorativa."""
    con_franja = hoja(tmp_path / "franja.png", franja_borde=True)
    assert es_hoja_en_blanco(con_franja)


def test_el_ruido_del_sensor_tampoco(tmp_path):
    sucia = hoja(tmp_path / "ruido.png", gris_papel=232, ruido=True)
    assert es_hoja_en_blanco(sucia)


def test_una_hoja_apenas_con_un_sello_no_esta_en_blanco(tmp_path):
    """Un folio, un sello o una firma suelta son contenido. Este es el
    caso que separa una detección útil de una que borra trabajo ajeno."""
    sellada = hoja(tmp_path / "sello.png", mancha=(700, 1400, 150))
    assert not es_hoja_en_blanco(sellada)


def test_una_hoja_con_solo_su_numero_de_folio_no_esta_en_blanco(tmp_path):
    """El caso que obligó a bajar el umbral y a recortar menos borde.

    Un folio al pie mide 0,05 % de cobertura. Con el umbral original
    (0,3 %) y un recorte del 5 % de cada borde, esa página se daba por
    vacía por partida doble: el número quedaba fuera del área medida Y
    aun dentro no habría alcanzado el umbral.
    """
    con_folio = hoja(tmp_path / "folio.png", mancha=(1100, 1650, 30))
    assert not es_hoja_en_blanco(con_folio)


def test_las_perforaciones_de_carpeta_no_son_contenido_pero_tampoco_borran(
        tmp_path):
    """Tres agujeros de carpeta miden 0,18 %: más que un folio.

    No se puede separar "tiene agujeros" de "tiene una marca chiquita" con
    una sola medida de cobertura, así que se elige el lado seguro: una
    hoja perforada NO se marca como vacía. Se pierde una detección; no se
    pierde una página.
    """
    perforada = hoja(tmp_path / "perforada.png", perforaciones=True)
    assert not es_hoja_en_blanco(perforada)


def test_una_raya_de_suciedad_en_el_vidrio_desactiva_la_deteccion(tmp_path):
    """Limitación conocida, y anotada acá para que se sepa que es a
    propósito: la suciedad en el vidrio del alimentador deja una raya
    vertical en TODAS las hojas, y esa raya es contenido para cualquier
    medida de cobertura.

    El resultado es que no se detecta ninguna hoja vacía. Molesto, pero es
    la dirección correcta del error: se dejan páginas de más, no se borran
    páginas con contenido.
    """
    rayada = hoja(tmp_path / "rayada.png", raya_vertical=True)
    assert not es_hoja_en_blanco(rayada)


def test_el_ruido_del_sensor_se_promedia_al_reducir(tmp_path):
    """Por qué el umbral puede estar tan cerca de cero: al reducir la
    imagen para medirla, el ruido se promedia y desaparece. Una hoja vacía
    da 0,0000 % incluso simulando un sensor muy sucio."""
    for sigma in (8, 20, 35):
        ruidosa = hoja(tmp_path / f"ruido{sigma}.png", ruido_sigma=sigma)
        assert cobertura_de_tinta(ruidosa) < 0.0001, (
            f"con σ={sigma} el ruido se cuenta como tinta")
        assert es_hoja_en_blanco(ruidosa)


def test_una_sola_linea_de_texto_no_esta_en_blanco(tmp_path):
    una = hoja(tmp_path / "una.png", texto_lineas=1)
    assert not es_hoja_en_blanco(una)


def test_papel_amarillento_sigue_estando_en_blanco(tmp_path):
    """Papel reciclado o viejo: más oscuro, pero sin nada escrito."""
    viejo = hoja(tmp_path / "viejo.png", gris_papel=218)
    assert es_hoja_en_blanco(viejo)


def test_la_cobertura_crece_con_el_texto(tmp_path):
    poco = cobertura_de_tinta(hoja(tmp_path / "a.png", texto_lineas=2))
    mucho = cobertura_de_tinta(hoja(tmp_path / "b.png", texto_lineas=20))
    assert 0 <= poco < mucho


def test_una_hoja_toda_negra_no_esta_en_blanco(tmp_path):
    ruta = tmp_path / "negra.png"
    Image.new("L", A4, 0).save(ruta)
    assert not es_hoja_en_blanco(ruta)
    assert cobertura_de_tinta(ruta) > 0.9


# ── Lo que NO se puede leer ───────────────────────────────────────────────────

def test_una_imagen_ilegible_no_es_una_hoja_en_blanco(tmp_path):
    """Ilegible y vacía son cosas distintas. Confundirlas haría que un
    archivo dañado se borre solo, que es la peor forma de perder una
    página: sin aviso y sin rastro."""
    roto = tmp_path / "roto.png"
    roto.write_bytes(b"esto no es un PNG")
    assert cobertura_de_tinta(roto) == -1.0
    assert not es_hoja_en_blanco(roto)


def test_un_archivo_que_no_existe_tampoco(tmp_path):
    assert not es_hoja_en_blanco(tmp_path / "fantasma.png")


# ── Sobre listas ──────────────────────────────────────────────────────────────

def test_hojas_en_blanco_devuelve_las_posiciones(tmp_path):
    """El caso real: un taco dúplex donde algunas hojas eran de una cara."""
    rutas = [
        hoja(tmp_path / "1f.png", texto_lineas=12),   # frente
        hoja(tmp_path / "1d.png"),                    # dorso vacío
        hoja(tmp_path / "2f.png", texto_lineas=9),
        hoja(tmp_path / "2d.png", texto_lineas=7),    # esta sí tiene dorso
        hoja(tmp_path / "3f.png", texto_lineas=4),
        hoja(tmp_path / "3d.png"),                    # dorso vacío
    ]
    assert hojas_en_blanco(rutas) == [1, 5]


def test_un_umbral_mas_exigente_detecta_menos(tmp_path):
    apenas = hoja(tmp_path / "apenas.png", texto_lineas=1)
    assert not es_hoja_en_blanco(apenas)
    # Con un umbral muy alto, hasta una línea entra como "vacía"
    assert es_hoja_en_blanco(apenas, cobertura=0.5)


def test_el_umbral_deja_pasar_cualquier_marca_real(tmp_path):
    """El umbral no está "en el medio" de nada: está apenas por encima de
    cero. Una hoja vacía mide 0,0000 % y la marca real más chica que se
    probó —un folio al pie— mide 0,05 %, así que hay un factor de 2 entre
    el umbral y lo más chico que hay que conservar."""
    assert 0 < COBERTURA_VACIA < 0.0005

    vacia_ = cobertura_de_tinta(hoja(tmp_path / "v.png"))
    folio = cobertura_de_tinta(hoja(tmp_path / "f.png", mancha=(1100, 1650, 30)))
    assert vacia_ < COBERTURA_VACIA < folio, (
        f"vacía={vacia_:.5f}  umbral={COBERTURA_VACIA}  folio={folio:.5f}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Dos pasadas: frentes y dorsos
# ═══════════════════════════════════════════════════════════════════════════════

def test_intercalar_con_los_dorsos_al_reves():
    """El caso de verdad. Se pasa el taco (frentes 1,2,3), se lo da vuelta
    y se lo pasa de nuevo: los dorsos salen 3,2,1 porque la última hoja
    quedó arriba."""
    frentes = ["f1", "f2", "f3"]
    dorsos = ["d3", "d2", "d1"]
    assert intercalar(frentes, dorsos) == ["f1", "d1", "f2", "d2", "f3", "d3"]


def test_intercalar_sin_invertir():
    """Para el alimentador que devuelve el taco en el mismo orden, o para
    quien ya lo ordenó a mano."""
    assert intercalar(["f1", "f2"], ["d1", "d2"], dorsos_al_reves=False) == [
        "f1", "d1", "f2", "d2"]


def test_intercalar_una_sola_hoja():
    assert intercalar(["f1"], ["d1"]) == ["f1", "d1"]


def test_intercalar_sin_dorsos_deja_los_frentes():
    assert intercalar(["f1", "f2"], []) == ["f1", "f2"]


def test_intercalar_sin_frentes():
    assert intercalar([], ["d1", "d2"]) == ["d2", "d1"]


def test_intercalar_con_cantidades_distintas_no_inventa_nada():
    """El alimentador tomó dos hojas juntas en una de las pasadas. No se
    puede adivinar cuál falta, así que se intercala hasta donde alcanza y
    el resto va al final."""
    salida = intercalar(["f1", "f2", "f3"], ["d3", "d1"])
    assert len(salida) == 5
    assert salida[0] == "f1"
    assert "f3" in salida


def test_intercalar_no_toca_las_listas_originales():
    frentes, dorsos = ["f1", "f2"], ["d2", "d1"]
    intercalar(frentes, dorsos)
    assert frentes == ["f1", "f2"]
    assert dorsos == ["d2", "d1"], "invertir no debe modificar la lista recibida"


def test_descuadre_avisa_cuando_las_pasadas_no_coinciden():
    """Casi siempre significa que el alimentador tomó dos hojas juntas.
    Conviene decirlo antes de intercalar: el documento va a quedar mal y no
    de forma evidente."""
    assert descuadre(["f1", "f2", "f3"], ["d3", "d2", "d1"]) == 0
    assert descuadre(["f1", "f2", "f3"], ["d2", "d1"]) == 1


def test_intercalar_de_punta_a_punta_con_rutas(tmp_path):
    """Con las rutas que devolvería el escáner, para ver que el orden final
    es el que uno leería en el papel."""
    frentes = [hoja(tmp_path / f"frente{i}.png", texto_lineas=3)
               for i in (1, 2, 3)]
    dorsos = [hoja(tmp_path / f"dorso{i}.png", texto_lineas=2)
              for i in (3, 2, 1)]

    final = intercalar(frentes, dorsos)
    assert [p.name for p in final] == [
        "frente1.png", "dorso1.png",
        "frente2.png", "dorso2.png",
        "frente3.png", "dorso3.png"]
