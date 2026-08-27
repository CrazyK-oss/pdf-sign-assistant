"""
tests/test_documento_escaneado.py
============================================================
Tests del modelo de la herramienta "Escanear a PDF".

Lo que más se cubre acá es el reordenamiento: es la parte donde un error
de índice no revienta nada, simplemente deja el PDF con las páginas
cambiadas de lugar, y eso se descubre tarde y mal.

Sin Qt ni escáner: corren en el CI liviano.
"""

from __future__ import annotations

import datetime as dt

import pytest

from modules.documento_escaneado import (
    DocumentoEscaneado,
    con_extension_pdf,
    es_imagen,
    filtrar_imagenes,
    sanear_nombre,
)


@pytest.fixture
def doc():
    """Documento de 4 páginas, para no repetir el armado en cada test."""
    d = DocumentoEscaneado()
    for i in range(1, 5):
        d.agregar(f"/tmp/p{i}.png")
    return d


def orden(d: DocumentoEscaneado) -> list[str]:
    return [p.ruta.name for p in d.paginas]


# ── Alta de páginas ───────────────────────────────────────────────────────────

def test_agregar_va_al_final():
    d = DocumentoEscaneado()
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
    d = DocumentoEscaneado()
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
    d = DocumentoEscaneado()
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
    d = DocumentoEscaneado()
    d.agregar(real)
    d.agregar(tmp_path / "fantasma.png")

    faltan = d.faltantes()
    assert [p.ruta.name for p in faltan] == ["fantasma.png"]


def test_nombre_sugerido_no_lleva_dos_puntos():
    d = DocumentoEscaneado()
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
