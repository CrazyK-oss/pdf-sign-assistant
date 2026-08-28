"""
tests/test_documento.py
============================================================
Tests del modelo que comparten las herramientas que arman PDFs.

Lo que más se cubre acá es el reordenamiento: es la parte donde un error
de índice no revienta nada, simplemente deja el PDF con las páginas
cambiadas de lugar, y eso se descubre tarde y mal.

La segunda mitad cubre lo que trajo "Unir y dividir": páginas que vienen
de un PDF en vez del escáner, los subconjuntos y el parseo de rangos que
escribe el usuario.

Sin Qt ni escáner: corren en el CI liviano.
"""

from __future__ import annotations

import datetime as dt

import pytest

from modules.documento import (
    ORIGEN_ESCANER,
    ORIGEN_IMAGEN,
    ORIGEN_PDF,
    Documento,
    con_extension_pdf,
    es_imagen,
    es_pdf,
    filtrar_imagenes,
    filtrar_pdfs,
    filtrar_soportados,
    formatear_rangos,
    parsear_rangos,
    sanear_nombre,
)


@pytest.fixture
def doc():
    """Documento de 4 páginas, para no repetir el armado en cada test."""
    d = Documento()
    for i in range(1, 5):
        d.agregar(f"/tmp/p{i}.png")
    return d


def orden(d: Documento) -> list[str]:
    return [p.ruta.name for p in d.paginas]


# ── Alta de páginas ───────────────────────────────────────────────────────────

def test_agregar_va_al_final():
    d = Documento()
    d.agregar("/tmp/a.png")
    d.agregar("/tmp/b.png")
    assert orden(d) == ["a.png", "b.png"]
    assert d.total == 2
    assert not d.vacio


def test_los_ids_son_unicos_y_no_se_reciclan(doc):
    """Si un id se reutilizara tras borrar, la UI podría actuar sobre la
    página equivocada."""
    ids_iniciales = [p.id for p in doc.paginas]
    assert len(set(ids_iniciales)) == 4

    doc.quitar(ids_iniciales[1])
    nueva = doc.agregar("/tmp/nueva.png")
    assert nueva.id not in ids_iniciales


def test_agregar_en_una_posicion_concreta(doc):
    ids = [p.id for p in doc.paginas]
    doc.agregar("/tmp/intercalada.png", indice=2)
    assert orden(doc) == ["p1.png", "p2.png", "intercalada.png",
                          "p3.png", "p4.png"]
    # Las que ya estaban conservan su id pese al corrimiento
    assert [p.id for p in doc.paginas if p.id in ids] == ids


def test_agregar_varias_conserva_el_orden():
    d = Documento()
    d.agregar_varias(["/tmp/1.png", "/tmp/2.png", "/tmp/3.png"])
    assert orden(d) == ["1.png", "2.png", "3.png"]
    # Las importadas no son temporales: no hay que borrarlas al cerrar
    assert d.rutas_temporales() == []


def test_las_escaneadas_si_son_temporales(doc):
    assert len(doc.rutas_temporales()) == 4


# ── Reordenar ─────────────────────────────────────────────────────────────────

def test_mover_hacia_arriba_y_abajo(doc):
    tercera = doc.paginas[2].id

    assert doc.mover(tercera, -1) is True
    assert orden(doc) == ["p1.png", "p3.png", "p2.png", "p4.png"]

    assert doc.mover(tercera, 1) is True
    assert orden(doc) == ["p1.png", "p2.png", "p3.png", "p4.png"]


def test_los_extremos_no_dan_la_vuelta(doc):
    """Subir la primera o bajar la última no debe teletransportarlas."""
    assert doc.mover(doc.paginas[0].id, -1) is False
    assert doc.mover(doc.paginas[-1].id, 1) is False
    assert orden(doc) == ["p1.png", "p2.png", "p3.png", "p4.png"]


def test_mover_una_pagina_que_ya_no_esta(doc):
    id_muerto = doc.paginas[0].id
    doc.quitar(id_muerto)
    assert doc.mover(id_muerto, 1) is False
    assert doc.rotar(id_muerto, 90) is False


def test_mover_a_una_posicion(doc):
    ultima = doc.paginas[3].id
    assert doc.mover_a(ultima, 0) is True
    assert orden(doc) == ["p4.png", "p1.png", "p2.png", "p3.png"]


def test_mover_a_una_posicion_fuera_de_rango_se_recorta(doc):
    primera = doc.paginas[0].id
    assert doc.mover_a(primera, 99) is True
    assert orden(doc)[-1] == "p1.png"


def test_invertir(doc):
    doc.invertir()
    assert orden(doc) == ["p4.png", "p3.png", "p2.png", "p1.png"]


def test_quitar_devuelve_la_pagina_y_reordena(doc):
    segunda = doc.paginas[1].id
    quitada = doc.quitar(segunda)
    assert quitada is not None and quitada.ruta.name == "p2.png"
    assert orden(doc) == ["p1.png", "p3.png", "p4.png"]
    assert doc.indice_de(segunda) == -1
    assert doc.quitar(segunda) is None       # ya no está: no debe explotar


# ── Rotación ──────────────────────────────────────────────────────────────────

def test_la_rotacion_se_acumula_y_da_la_vuelta(doc):
    p = doc.paginas[0]
    doc.rotar(p.id, 90)
    assert p.rotacion == 90
    doc.rotar(p.id, 90)
    assert p.rotacion == 180
    doc.rotar(p.id, 180)
    assert p.rotacion == 0, "360° debe volver a 0, no quedar en 360"


def test_rotar_en_negativo(doc):
    p = doc.paginas[0]
    doc.rotar(p.id, -90)
    assert p.rotacion == 270


def test_rotar_todas(doc):
    doc.rotar(doc.paginas[0].id, 90)
    doc.rotar_todas(90)
    assert [p.rotacion for p in doc.paginas] == [180, 90, 90, 90]


# ── Estado y presentación ─────────────────────────────────────────────────────

def test_descripcion_singular_y_plural():
    d = Documento()
    assert d.descripcion() == "Sin páginas todavía"
    d.agregar("/tmp/a.png")
    assert d.descripcion() == "1 página"
    d.agregar("/tmp/b.png")
    assert d.descripcion() == "2 páginas"


def test_resumen_rotaciones(doc):
    assert doc.resumen_rotaciones() == ""
    doc.rotar(doc.paginas[0].id, 90)
    assert doc.resumen_rotaciones() == "1 girada"
    doc.rotar(doc.paginas[1].id, 90)
    assert doc.resumen_rotaciones() == "2 giradas"


def test_faltantes_detecta_los_archivos_que_no_estan(tmp_path):
    real = tmp_path / "real.png"
    real.write_bytes(b"x")
    d = Documento()
    d.agregar(real)
    d.agregar(tmp_path / "fantasma.png")

    faltan = d.faltantes()
    assert [p.ruta.name for p in faltan] == ["fantasma.png"]


def test_nombre_sugerido_no_lleva_dos_puntos():
    d = Documento()
    nombre = d.nombre_sugerido(dt.datetime(2026, 8, 27, 14, 30))
    assert nombre == "Escaneo 2026-08-27 14-30.pdf"
    assert ":" not in nombre, "Windows no admite ':' en un nombre de archivo"


def test_limpiar(doc):
    doc.limpiar()
    assert doc.vacio and doc.total == 0


# ── Nombres de archivo ────────────────────────────────────────────────────────

@pytest.mark.parametrize("entrada, esperado", [
    ("Contrato 2026", "Contrato 2026"),
    ('Con:tra/to*?"', "Contrato"),
    ("   ", "Escaneo"),
    ("", "Escaneo"),
    ("nombre.", "nombre"),          # Windows recorta el punto final en silencio
    ("nombre   ", "nombre"),
])
def test_sanear_nombre(entrada, esperado):
    assert sanear_nombre(entrada) == esperado


def test_sanear_nombre_esquiva_los_reservados_de_windows():
    """Un archivo llamado CON.pdf falla al crearse en Windows."""
    assert sanear_nombre("CON") == "_CON"
    assert sanear_nombre("lpt1.pdf") == "_lpt1.pdf"


def test_sanear_nombre_acota_el_largo():
    assert len(sanear_nombre("a" * 300)) == 120


@pytest.mark.parametrize("entrada, esperado", [
    ("Contrato", "Contrato.pdf"),
    ("Contrato.pdf", "Contrato.pdf"),
    ("Contrato.PDF", "Contrato.PDF"),      # ya la tiene: no se duplica
    ("", "Escaneo.pdf"),
])
def test_con_extension_pdf(entrada, esperado):
    assert con_extension_pdf(entrada) == esperado


def test_es_imagen_y_filtrar():
    assert es_imagen("foto.JPG") and es_imagen("x.tiff")
    assert not es_imagen("documento.pdf")
    assert filtrar_imagenes(
        ["a.png", "b.pdf", "c.jpeg", "d.txt"]) == ["a.png", "c.jpeg"]


# ═══════════════════════════════════════════════════════════════════════════════
#  Páginas que vienen de un PDF
# ═══════════════════════════════════════════════════════════════════════════════

def test_agregar_pdf_numera_las_paginas_desde_cero():
    """El índice es la página dentro del archivo, 0-based, porque es lo
    que van a pedirle a PyMuPDF."""
    d = Documento()
    creadas = d.agregar_pdf("/tmp/Contrato.pdf", 3)

    assert [p.indice for p in creadas] == [0, 1, 2]
    assert all(p.origen == ORIGEN_PDF for p in creadas)
    assert all(p.ruta.name == "Contrato.pdf" for p in creadas)


def test_un_pdf_abierto_nunca_es_temporal():
    """Marcarlo temporal haría que la app borre el documento del usuario
    al cerrarse. Es el peor error posible de este módulo."""
    d = Documento()
    d.agregar_pdf("/tmp/Contrato.pdf", 2)
    assert d.rutas_temporales() == []


def test_agregar_pdf_acepta_un_giro_extra_por_pagina():
    """Es giro *adicional*: la rotación que el PDF ya trae adentro viaja en
    el archivo y la aplica quien lo lee. Copiarla acá la aplicaría dos
    veces y las páginas quedarían de lado."""
    d = Documento()
    d.agregar_pdf("/tmp/x.pdf", 3, rotaciones=[0, 90, 270])
    assert [p.rotacion for p in d.paginas] == [0, 90, 270]


def test_agregar_pdf_sin_rotaciones_no_gira_nada():
    d = Documento()
    d.agregar_pdf("/tmp/x.pdf", 3)
    assert [p.rotacion for p in d.paginas] == [0, 0, 0]


def test_agregar_pdf_en_una_posicion_mantiene_el_orden_interno():
    """Insertar un PDF de 3 páginas en el medio no debe darlas vuelta."""
    d = Documento()
    d.agregar("/tmp/a.png")
    d.agregar("/tmp/b.png")
    d.agregar_pdf("/tmp/medio.pdf", 3, indice=1)

    assert [p.ruta.name for p in d.paginas] == [
        "a.png", "medio.pdf", "medio.pdf", "medio.pdf", "b.png"]
    assert [p.indice for p in d.paginas[1:4]] == [0, 1, 2]


def test_agregar_pdf_de_cero_paginas_no_agrega_nada():
    d = Documento()
    assert d.agregar_pdf("/tmp/vacio.pdf", 0) == []
    assert d.vacio


def test_mixto_distingue_los_tres_casos():
    solo_imagenes = Documento()
    solo_imagenes.agregar("/tmp/a.png")
    assert not solo_imagenes.tiene_pdf and not solo_imagenes.mixto

    solo_pdf = Documento()
    solo_pdf.agregar_pdf("/tmp/a.pdf", 2)
    assert solo_pdf.tiene_pdf and not solo_pdf.mixto

    mezcla = Documento()
    mezcla.agregar_pdf("/tmp/a.pdf", 1)
    mezcla.agregar("/tmp/b.png")
    assert mezcla.tiene_pdf and mezcla.mixto


def test_archivos_pdf_no_repite_y_conserva_el_orden():
    d = Documento()
    d.agregar_pdf("/tmp/uno.pdf", 2)
    d.agregar_pdf("/tmp/dos.pdf", 1)
    d.agregar_pdf("/tmp/uno.pdf", 1)
    assert [r.name for r in d.archivos_pdf()] == ["uno.pdf", "dos.pdf"]


def test_la_clave_de_previa_ignora_el_id():
    """Dos entradas que apuntan a la misma página del mismo PDF se ven
    igual: tienen que compartir la miniatura ya renderizada."""
    d = Documento()
    a = d.agregar("/tmp/x.pdf", origen=ORIGEN_PDF, indice_pagina=2)
    b = d.agregar("/tmp/x.pdf", origen=ORIGEN_PDF, indice_pagina=2)
    assert a.id != b.id
    assert a.clave == b.clave


def test_la_clave_de_previa_cambia_al_girar():
    d = Documento()
    p = d.agregar("/tmp/x.pdf", origen=ORIGEN_PDF, indice_pagina=0)
    antes = p.clave
    d.rotar(p.id, 90)
    assert p.clave != antes


def test_paginas_distintas_del_mismo_pdf_no_comparten_clave():
    d = Documento()
    a = d.agregar("/tmp/x.pdf", origen=ORIGEN_PDF, indice_pagina=0)
    b = d.agregar("/tmp/x.pdf", origen=ORIGEN_PDF, indice_pagina=1)
    assert a.clave != b.clave


def test_la_descripcion_de_una_pagina_de_pdf_dice_cual_es():
    """1-based en el texto: es el número que el usuario ve en su lector."""
    d = Documento()
    p = d.agregar("/tmp/Contrato.pdf", origen=ORIGEN_PDF, indice_pagina=4)
    assert p.descripcion() == "Contrato.pdf · página 5"


def test_la_descripcion_de_una_imagen_es_solo_el_nombre():
    d = Documento()
    p = d.agregar("/tmp/hoja.png", origen=ORIGEN_ESCANER)
    assert p.descripcion() == "hoja.png"


@pytest.mark.parametrize("origen, etiqueta", [
    (ORIGEN_ESCANER, "Escaneada"),
    (ORIGEN_IMAGEN, "Imagen"),
    (ORIGEN_PDF, "PDF"),
])
def test_etiqueta_de_origen(origen, etiqueta):
    d = Documento()
    assert d.agregar("/tmp/x", origen=origen).etiqueta_origen() == etiqueta


# ═══════════════════════════════════════════════════════════════════════════════
#  Quitar varias, subconjuntos y partición
# ═══════════════════════════════════════════════════════════════════════════════

def test_quitar_varias_saca_todas_de_una(doc):
    ids = [doc.paginas[0].id, doc.paginas[2].id]
    sacadas = doc.quitar_varias(ids)
    assert [p.ruta.name for p in sacadas] == ["p1.png", "p3.png"]
    assert orden(doc) == ["p2.png", "p4.png"]


def test_quitar_varias_ignora_ids_que_no_estan(doc):
    assert doc.quitar_varias([999]) == []
    assert doc.total == 4


def test_subconjunto_toma_las_posiciones_pedidas(doc):
    trozo = doc.subconjunto([2, 0])
    assert orden(trozo) == ["p3.png", "p1.png"]


def test_subconjunto_no_toca_el_original(doc):
    """El original se sigue usando para armar los otros trozos: si
    `subconjunto` compartiera las páginas, mover una en el trozo
    reordenaría el documento de origen."""
    trozo = doc.subconjunto([0, 1])
    trozo.invertir()
    assert orden(doc) == ["p1.png", "p2.png", "p3.png", "p4.png"]
    assert orden(trozo) == ["p2.png", "p1.png"]


def test_subconjunto_ignora_posiciones_fuera_de_rango(doc):
    assert orden(doc.subconjunto([0, 99, -5])) == ["p1.png"]


def test_un_trozo_no_manda_a_borrar_los_temporales(doc):
    """Las páginas del original son temporales; el trozo apunta a los
    mismos archivos. Si el trozo también los diera por temporales, cerrarlo
    borraría lo que el documento de origen todavía necesita."""
    assert doc.rutas_temporales()
    assert doc.subconjunto([0, 1]).rutas_temporales() == []


def test_partir_cada_deja_el_resto_en_el_ultimo_trozo():
    d = Documento()
    for i in range(1, 8):
        d.agregar(f"/tmp/p{i}.png")
    trozos = d.partir_cada(3)
    assert [t.total for t in trozos] == [3, 3, 1]
    assert orden(trozos[-1]) == ["p7.png"]


def test_partir_cada_uno_da_un_trozo_por_pagina(doc):
    assert [t.total for t in doc.partir_cada(1)] == [1, 1, 1, 1]


def test_partir_por_mas_que_el_total_da_un_solo_trozo(doc):
    trozos = doc.partir_cada(50)
    assert len(trozos) == 1 and trozos[0].total == 4


def test_partir_por_cero_no_hace_un_bucle_infinito(doc):
    """Un 0 llegado de un campo de texto no debe colgar la aplicación."""
    assert [t.total for t in doc.partir_cada(0)] == [1, 1, 1, 1]


# ═══════════════════════════════════════════════════════════════════════════════
#  Nombres sugeridos
# ═══════════════════════════════════════════════════════════════════════════════

def test_sin_base_el_nombre_sugerido_es_la_fecha():
    d = Documento()
    assert d.nombre_sugerido(dt.datetime(2026, 8, 27, 14, 30)) == \
        "Escaneo 2026-08-27 14-30.pdf"


def test_con_base_el_nombre_sugerido_no_pisa_el_original():
    """Guardar encima del PDF de partida, con páginas quitadas, es una
    pérdida de datos silenciosa."""
    d = Documento(base_nombre="Contrato")
    assert d.nombre_sugerido() == "Contrato (editado).pdf"


def test_limpiar_tambien_olvida_el_nombre_base():
    d = Documento(base_nombre="Contrato")
    d.agregar_pdf("/tmp/Contrato.pdf", 1)
    d.limpiar()
    assert d.vacio
    assert "Escaneo" in d.nombre_sugerido()


def test_nombre_de_trozo_ordena_bien_en_el_explorador():
    """Sin ceros a la izquierda, Windows ordena la parte 10 entre la 1 y
    la 2 y el usuario arma el documento al revés."""
    d = Documento(base_nombre="Contrato")
    nombres = [d.nombre_de_trozo(i, 12) for i in (1, 2, 10)]
    assert nombres == ["Contrato (parte 01 de 12).pdf",
                       "Contrato (parte 02 de 12).pdf",
                       "Contrato (parte 10 de 12).pdf"]
    assert sorted(nombres) == nombres


def test_nombre_de_trozo_sin_base():
    assert Documento().nombre_de_trozo(1, 2) == "Documento (parte 1 de 2).pdf"


# ═══════════════════════════════════════════════════════════════════════════════
#  Rangos escritos por el usuario
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("texto, esperado", [
    ("1", [0]),
    ("1-3", [0, 1, 2]),
    ("1-3, 5", [0, 1, 2, 4]),
    ("1-3,5", [0, 1, 2, 4]),
    ("  2 , 4  ", [1, 3]),
    ("1-3; 5", [0, 1, 2, 4]),          # el punto y coma también vale
    ("1 - 3", [0, 1, 2]),
    ("2-2", [1]),
])
def test_parsear_rangos(texto, esperado):
    assert parsear_rangos(texto, 9) == esperado


def test_un_rango_al_reves_se_expande_al_reves():
    """Es la forma cómoda de invertir un tramo; prohibirlo no aportaría nada."""
    assert parsear_rangos("5-3", 9) == [4, 3, 2]


def test_los_rangos_no_repiten_paginas():
    """Pedir "1-3, 2" no debe meter la página 2 dos veces en el PDF."""
    assert parsear_rangos("1-3, 2", 9) == [0, 1, 2]


def test_el_orden_escrito_se_respeta():
    """Sirve para reordenar: "3,1,2" es una permutación, no un conjunto."""
    assert parsear_rangos("3,1,2", 9) == [2, 0, 1]


def test_parsear_rangos_acepta_los_guiones_largos():
    """Word y los correos convierten el guion en raya al escribir."""
    assert parsear_rangos("1–3", 9) == parsear_rangos("1-3", 9)
    assert parsear_rangos("1—3", 9) == parsear_rangos("1-3", 9)


@pytest.mark.parametrize("texto", ["", "   ", ",", " , , "])
def test_un_rango_vacio_pide_un_ejemplo(texto):
    with pytest.raises(ValueError, match="1-3"):
        parsear_rangos(texto, 9)


@pytest.mark.parametrize("texto", ["a", "1-a", "1..3", "-2", "1-", "1,,x"])
def test_un_rango_ilegible_lo_dice_con_el_texto_del_usuario(texto):
    with pytest.raises(ValueError, match="entiendo"):
        parsear_rangos(texto, 9)


@pytest.mark.parametrize("texto", ["0", "10", "1-10", "10-1"])
def test_una_pagina_que_no_existe_se_avisa_con_el_total(texto):
    with pytest.raises(ValueError, match="tiene 9"):
        parsear_rangos(texto, 9)


def test_parsear_rangos_sobre_un_documento_vacio():
    with pytest.raises(ValueError, match="no tiene páginas"):
        parsear_rangos("1", 0)


def test_el_mensaje_de_error_se_le_puede_mostrar_al_usuario():
    """No debe tener jerga ni nombres de función: va tal cual a la pantalla."""
    with pytest.raises(ValueError) as e:
        parsear_rangos("1-99", 9)
    assert str(e.value) == "La página 99 no existe: el documento tiene 9."


@pytest.mark.parametrize("indices, esperado", [
    ([], ""),
    ([0], "1"),
    ([0, 1, 2], "1-3"),
    ([0, 1, 2, 4], "1-3, 5"),
    ([0, 2, 4], "1, 3, 5"),
    ([4, 3, 2], "5, 4, 3"),          # desordenado: se muestra tal cual
])
def test_formatear_rangos(indices, esperado):
    assert formatear_rangos(indices) == esperado


def test_formatear_y_parsear_son_inversos():
    indices = [0, 1, 2, 4, 7, 8]
    assert parsear_rangos(formatear_rangos(indices), 9) == indices


# ═══════════════════════════════════════════════════════════════════════════════
#  Filtros de arrastrar y soltar
# ═══════════════════════════════════════════════════════════════════════════════

def test_es_pdf():
    assert es_pdf("Contrato.PDF") and es_pdf("x.pdf")
    assert not es_pdf("foto.png")


def test_filtrar_pdfs():
    assert filtrar_pdfs(["a.png", "b.pdf", "c.PDF"]) == ["b.pdf", "c.PDF"]


def test_filtrar_soportados_conserva_el_orden_en_que_se_soltaron():
    """Si alguien arrastra varios archivos juntos, el orden en que los
    soltó es el orden en que espera verlos."""
    assert filtrar_soportados(
        ["b.pdf", "a.png", "notas.txt", "c.jpeg"]) == ["b.pdf", "a.png", "c.jpeg"]
