"""
tests/test_trabajo.py
============================================================
Tests del modelo de dominio (modules/trabajo.py).

No necesitan Qt ni pantalla: son lógica pura, así que corren en
cualquier runner de CI sin display virtual. Ejecutar con:

    pytest -q
"""

from pathlib import Path

import pytest

from modules.trabajo import TrabajoFirma, formatear_paginas, parsear_paginas


# ── formatear_paginas ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("entrada,esperado", [
    ([], "—"),
    ([0], "1"),
    ([0, 1, 2, 3], "1-4"),
    ([0, 2, 4], "1, 3, 5"),
    ([0, 1, 2, 5, 7, 8], "1-3, 6, 8-9"),
    ([4, 0, 4, 1], "1-2, 5"),          # desordenado y con duplicados
])
def test_formatear_paginas(entrada, esperado):
    assert formatear_paginas(entrada) == esperado


# ── parsear_paginas ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto,esperado", [
    ("1,3,5",     [0, 2, 4]),
    ("1, 3-5",    [0, 2, 3, 4]),
    ("5-3",       [2, 3, 4]),          # rango invertido
    ("1,50",      [0]),                # recorta fuera de rango
    ("1,abc,,3",  [0, 2]),             # ignora basura
    ("0,-2,2",    [1]),                # descarta cero y negativos
    ("",          []),
    ("1;3",       [0, 2]),             # acepta punto y coma
])
def test_parsear_paginas(texto, esperado):
    assert parsear_paginas(texto, total=10) == esperado


# ── Selección ─────────────────────────────────────────────────────────────────

def nuevo(total=5) -> TrabajoFirma:
    return TrabajoFirma(ruta_pdf=Path("documento.pdf"), total_paginas=total)


def test_set_paginas_normaliza():
    t = nuevo()
    t.set_paginas([4, 0, 2, 9, -1])     # 9 y -1 están fuera del documento
    assert t.paginas == [0, 2, 4]


def test_set_paginas_descarta_imagenes_de_paginas_quitadas():
    t = nuevo()
    t.set_paginas([0, 2, 4])
    t.asignar_imagen(2, "b.png")
    t.asignar_imagen(4, "c.png")
    t.rotar(4, 90)

    t.set_paginas([0, 2])
    assert 4 not in t.imagenes
    assert 4 not in t.rotaciones
    assert t.imagenes[2] == "b.png"     # la que sigue seleccionada se conserva


def test_alternar_pagina():
    t = nuevo()
    t.set_paginas([2])
    assert t.alternar_pagina(2) is False and t.paginas == []
    assert t.alternar_pagina(3) is True and t.paginas == [3]


# ── Imágenes ──────────────────────────────────────────────────────────────────

def test_asignar_imagen_rechaza_pagina_no_seleccionada():
    t = nuevo()
    t.set_paginas([0])
    with pytest.raises(ValueError):
        t.asignar_imagen(1, "x.png")


def test_pendientes_y_completo():
    t = nuevo()
    t.set_paginas([0, 2, 4])
    assert not t.completo
    assert t.paginas_pendientes() == [0, 2, 4]

    t.asignar_imagen(0, "a.png")
    t.asignar_imagen(2, "b.png")
    assert not t.completo
    assert t.paginas_listas() == [0, 2]

    t.asignar_imagen(4, "c.png")
    assert t.completo


def test_trabajo_sin_paginas_no_esta_completo():
    assert not nuevo().completo


def test_siguiente_pendiente_es_circular():
    t = nuevo()
    t.set_paginas([0, 2, 4])
    t.asignar_imagen(2, "b.png")
    assert t.siguiente_pendiente() == 0
    assert t.siguiente_pendiente(desde=2) == 4
    assert t.siguiente_pendiente(desde=4) == 0     # vuelve al principio


def test_siguiente_pendiente_sin_pendientes():
    t = nuevo()
    t.set_paginas([0])
    t.asignar_imagen(0, "a.png")
    assert t.siguiente_pendiente() is None


def test_quitar_imagen_limpia_rotacion():
    t = nuevo()
    t.set_paginas([1])
    t.asignar_imagen(1, "a.png")
    t.rotar(1, 90)
    t.quitar_imagen(1)
    assert t.rotacion(1) == 0
    assert t.paginas_pendientes() == [1]


# ── Rotación ──────────────────────────────────────────────────────────────────

def test_rotacion_acumula_y_vuelve_a_cero():
    t = nuevo()
    t.set_paginas([1])
    t.asignar_imagen(1, "a.png")
    assert t.rotar(1, 90) == 90
    assert t.rotar(1, 90) == 180
    assert t.rotar(1, 180) == 0
    assert 1 not in t.rotaciones      # 0 no se guarda


def test_rotacion_negativa():
    t = nuevo()
    t.set_paginas([1])
    t.asignar_imagen(1, "a.png")
    assert t.rotar(1, -90) == 270


def test_rotar_sin_imagen_falla():
    t = nuevo()
    t.set_paginas([1])
    with pytest.raises(ValueError):
        t.rotar(1, 90)


def test_rotacion_no_multiplo_de_90_falla():
    t = nuevo()
    t.set_paginas([1])
    t.asignar_imagen(1, "a.png")
    with pytest.raises(ValueError):
        t.rotar(1, 45)


# ── Textos ────────────────────────────────────────────────────────────────────

def test_descripcion_progreso():
    t = nuevo()
    assert t.descripcion_progreso() == "Sin páginas seleccionadas"

    t.set_paginas([0, 2, 4])
    assert t.descripcion_progreso() == "0 de 3 páginas listas"

    t.asignar_imagen(0, "a.png")
    assert t.descripcion_progreso() == "1 de 3 páginas listas"

    t.asignar_imagen(2, "b.png")
    t.asignar_imagen(4, "c.png")
    assert t.descripcion_progreso() == "3 páginas listas para guardar"


def test_resumen_para_correo():
    t = nuevo()
    t.set_paginas([0, 1, 2])
    resumen = t.resumen("contrato")
    assert "contrato" in resumen
    assert "1-3" in resumen
    assert "Total páginas firmadas: 3" in resumen


def test_etiqueta_paginas():
    t = nuevo(total=10)
    t.set_paginas([0, 1, 2, 5])
    assert t.etiqueta_paginas() == "1-3, 6"
