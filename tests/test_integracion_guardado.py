"""
tests/test_integracion_guardado.py
============================================================
Tests de integración del pipeline de guardado, que es el corazón de la
aplicación: imagen escaneada → PDF de una página → reemplazo dentro del
documento original.

Por qué están aparte
--------------------
A diferencia del resto de la suite, estos SÍ necesitan las dependencias
reales (PyQt6, PyMuPDF, Pillow, pypdf/reportlab), porque comprueban el
resultado de verdad: abren el PDF generado y miran los píxeles de cada
página. Por eso:

  - se saltean solos si falta alguna dependencia (`importorskip`), así el
    job liviano de CI —que sólo instala pytest y ruff— no se rompe;
  - llevan la marca `integracion`, para poder excluirlos con
    `-m "not integracion"`;
  - corren en el job de Release, que instala requirements.txt completo.

Qué cubren
----------
Que cada imagen aterrice en SU página, que las no elegidas queden
intactas, que la rotación se aplique y que los metadatos registren las
páginas firmadas. Eso último es lo que después lee el envío por correo.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("PyQt6", reason="Necesita las dependencias de la app")
pytest.importorskip("pymupdf", reason="Necesita PyMuPDF")
pytest.importorskip("PIL", reason="Necesita Pillow")

import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from modules.fase_guardar import (  # noqa: E402
    _WorkerGuardar,
    aplicar_rotacion,
    leer_paginas_firmadas,
)
from modules.trabajo import TrabajoFirma  # noqa: E402

pytestmark = pytest.mark.integracion

TIMEOUT = 90        # segundos para el worker


@pytest.fixture(scope="module")
def app():
    """Una sola QApplication para todo el módulo (Qt no admite dos)."""
    instancia = QApplication.instance() or QApplication(["tests"])
    yield instancia


@pytest.fixture
def pdf_origen(tmp_path) -> Path:
    """Documento de 9 páginas con texto identificable en cada una."""
    doc = pymupdf.open()
    for i in range(9):
        pagina = doc.new_page(width=595, height=842)
        pagina.insert_text((72, 100), f"Original pagina {i + 1}", fontsize=20)
    ruta = tmp_path / "documento.pdf"
    doc.save(str(ruta))
    doc.close()
    return ruta


def imagen_color(ruta: Path, color: tuple[int, int, int],
                 tamano=(1240, 1750)) -> Path:
    """Escaneo simulado: un color plano, fácil de reconocer después."""
    Image.new("RGB", tamano, color).save(ruta, dpi=(150, 150))
    return ruta


def ejecutar_worker(app, trabajo: TrabajoFirma, destino: Path) -> list[str]:
    """Corre el worker de guardado y devuelve los errores que emitió."""
    worker = _WorkerGuardar(trabajo, destino)
    errores: list[str] = []
    worker.error.connect(errores.append)
    worker.start()

    limite = time.time() + TIMEOUT
    while worker.isRunning() and time.time() < limite:
        app.processEvents()
        time.sleep(0.01)
    worker.wait(2000)
    app.processEvents()
    return errores


def color_dominante(pagina) -> tuple[int, int, int]:
    pix = pagina.get_pixmap(matrix=pymupdf.Matrix(0.15, 0.15))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return max(img.getcolors(img.size[0] * img.size[1]))[1]


def parecido(a, b, tolerancia=42) -> bool:
    return all(abs(x - y) <= tolerancia for x, y in zip(a, b))


# ── El caso central: varias páginas a la vez ──────────────────────────────────

def test_cada_imagen_va_a_su_pagina(app, pdf_origen, tmp_path):
    """Lo que más importa: que no se crucen las páginas.

    Se firman la 3, la 6 y la 8 con colores distintos y se comprueba en el
    PDF resultante que cada color quedó en su página, y que las demás no
    se tocaron.
    """
    colores = {2: (220, 60, 60), 5: (60, 160, 220), 7: (90, 200, 120)}

    trabajo = TrabajoFirma(ruta_pdf=pdf_origen, total_paginas=9)
    trabajo.set_paginas(list(colores))
    for pagina, color in colores.items():
        trabajo.asignar_imagen(
            pagina, str(imagen_color(tmp_path / f"firma_{pagina}.png", color)))

    destino = tmp_path / "firmado.pdf"
    assert ejecutar_worker(app, trabajo, destino) == []
    assert destino.is_file() and destino.stat().st_size > 0

    doc = pymupdf.open(destino)
    try:
        assert doc.page_count == 9, "no debe cambiar la cantidad de páginas"

        for pagina, color in colores.items():
            obtenido = color_dominante(doc[pagina])
            assert parecido(obtenido, color), (
                f"la página {pagina + 1} debería tener el color {color} "
                f"y tiene {obtenido}")

        # Las páginas no elegidas conservan su texto original
        for i in (0, 1, 3, 4, 6, 8):
            assert f"Original pagina {i + 1}" in doc[i].get_text()
    finally:
        doc.close()


def test_los_metadatos_registran_las_paginas_firmadas(app, pdf_origen, tmp_path):
    """Es lo que lee el envío por correo para armar el resumen."""
    trabajo = TrabajoFirma(ruta_pdf=pdf_origen, total_paginas=9)
    trabajo.set_paginas([0, 4])
    for pagina in (0, 4):
        trabajo.asignar_imagen(
            pagina, str(imagen_color(tmp_path / f"f{pagina}.png", (10, 10, 10))))

    destino = tmp_path / "con_metadatos.pdf"
    assert ejecutar_worker(app, trabajo, destino) == []
    assert leer_paginas_firmadas(destino) == [0, 4]


def test_una_sola_pagina(app, pdf_origen, tmp_path):
    """El caso más común no debe romperse por soportar varios."""
    trabajo = TrabajoFirma(ruta_pdf=pdf_origen, total_paginas=9)
    trabajo.set_paginas([3])
    trabajo.asignar_imagen(
        3, str(imagen_color(tmp_path / "una.png", (200, 120, 30))))

    destino = tmp_path / "una.pdf"
    assert ejecutar_worker(app, trabajo, destino) == []

    doc = pymupdf.open(destino)
    try:
        assert doc.page_count == 9
        assert parecido(color_dominante(doc[3]), (200, 120, 30))
        assert "Original pagina 3" in doc[2].get_text()
    finally:
        doc.close()


# ── Rotación ──────────────────────────────────────────────────────────────────

def test_la_rotacion_no_deforma_la_pagina(app, pdf_origen, tmp_path):
    """Rotar 90° una imagen apaisada debe dar una página vertical sana."""
    apaisada = imagen_color(tmp_path / "apaisada.png", (240, 200, 80),
                            tamano=(1750, 1240))

    trabajo = TrabajoFirma(ruta_pdf=pdf_origen, total_paginas=9)
    trabajo.set_paginas([1])
    trabajo.asignar_imagen(1, str(apaisada))
    trabajo.rotar(1, 90)

    destino = tmp_path / "rotada.pdf"
    assert ejecutar_worker(app, trabajo, destino) == []

    doc = pymupdf.open(destino)
    try:
        rect = doc[1].rect
        assert rect.height > rect.width, "tras rotar debería quedar vertical"
        assert parecido(color_dominante(doc[1]), (240, 200, 80))
    finally:
        doc.close()


def test_rotar_no_modifica_la_imagen_original(tmp_path):
    """La rotación se aplica sobre una copia: el escaneo no se toca."""
    original = imagen_color(tmp_path / "intacta.png", (10, 20, 30),
                            tamano=(400, 200))
    antes = original.read_bytes()

    ruta, temporal = aplicar_rotacion(str(original), 90)
    try:
        assert temporal is True
        assert Path(ruta) != original
        assert original.read_bytes() == antes          # sin tocar
        with Image.open(ruta) as img:
            assert img.size == (200, 400)              # dimensiones giradas
    finally:
        if temporal:
            Path(ruta).unlink(missing_ok=True)


# ── Errores ───────────────────────────────────────────────────────────────────

def test_falla_si_falta_una_imagen(app, pdf_origen, tmp_path):
    """Si el temporal del escaneo desapareció, hay que avisar, no escribir
    un PDF a medias."""
    trabajo = TrabajoFirma(ruta_pdf=pdf_origen, total_paginas=9)
    trabajo.set_paginas([0])
    trabajo.asignar_imagen(0, str(tmp_path / "no_existe.png"))

    destino = tmp_path / "fallido.pdf"
    errores = ejecutar_worker(app, trabajo, destino)

    assert errores, "debería reportar el error"
    assert not destino.exists(), "no debe quedar un PDF a medio escribir"


def test_falla_si_la_pagina_esta_fuera_de_rango(app, pdf_origen, tmp_path):
    trabajo = TrabajoFirma(ruta_pdf=pdf_origen, total_paginas=99)
    trabajo.set_paginas([50])            # el documento tiene 9
    trabajo.asignar_imagen(
        50, str(imagen_color(tmp_path / "x.png", (0, 0, 0))))

    errores = ejecutar_worker(app, trabajo, tmp_path / "rango.pdf")
    assert errores
    assert "9" in errores[0]             # menciona el total real
