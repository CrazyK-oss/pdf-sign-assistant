"""
tests/test_integracion_escaneo.py
============================================================
Tests de integración de la herramienta "Escanear a PDF".

Comprueban lo único que realmente importa del guardado: que el PDF salga
con las páginas que se pidieron, EN EL ORDEN que quedaron en pantalla, y
con la rotación aplicada. Para eso se abre el PDF resultante y se miran
los píxeles, no sólo la cantidad de páginas.

Como los de fase_guardar, necesitan las dependencias reales y por eso
llevan la marca `integracion` y se saltean solos en el CI liviano.
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

from modules.documento import Documento  # noqa: E402
from modules.herramienta_escaneo import _WorkerArmarPDF  # noqa: E402

pytestmark = pytest.mark.integracion

TIMEOUT = 90

ROJO = (220, 60, 60)
AZUL = (60, 140, 220)
VERDE = (90, 200, 120)


@pytest.fixture(scope="module")
def app(qapp):
    """La QApplication compartida (ver tests/conftest.py)."""
    return qapp


def imagen(ruta: Path, color, tamano=(620, 876)) -> Path:
    Image.new("RGB", tamano, color).save(ruta, dpi=(150, 150))
    return ruta


def ejecutar(app, paginas, destino: Path) -> list[str]:
    """Corre el worker y devuelve los errores que emitió."""
    worker = _WorkerArmarPDF(paginas, destino)
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
    pix = pagina.get_pixmap(matrix=pymupdf.Matrix(0.2, 0.2))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return max(img.getcolors(img.size[0] * img.size[1]))[1]


def parecido(a, b, tolerancia=42) -> bool:
    return all(abs(x - y) <= tolerancia for x, y in zip(a, b))


# ── El caso central ───────────────────────────────────────────────────────────

def test_las_paginas_salen_en_el_orden_de_la_lista(app, tmp_path):
    """Reordenar en pantalla tiene que reordenar en el PDF.

    Se arma rojo-azul-verde, se sube el verde al principio y se comprueba
    que el PDF quede verde-rojo-azul.
    """
    doc = Documento()
    doc.agregar(imagen(tmp_path / "r.png", ROJO))
    doc.agregar(imagen(tmp_path / "a.png", AZUL))
    verde = doc.agregar(imagen(tmp_path / "v.png", VERDE))

    doc.mover_a(verde.id, 0)

    destino = tmp_path / "orden.pdf"
    assert ejecutar(app, doc.paginas, destino) == []
    assert destino.is_file() and destino.stat().st_size > 0

    pdf = pymupdf.open(destino)
    try:
        assert pdf.page_count == 3
        for i, esperado in enumerate((VERDE, ROJO, AZUL)):
            obtenido = color_dominante(pdf[i])
            assert parecido(obtenido, esperado), (
                f"la página {i + 1} debería ser {esperado} y es {obtenido}")
    finally:
        pdf.close()


def test_la_rotacion_se_aplica_a_la_pagina_correcta(app, tmp_path):
    """Girar 90° una hoja apaisada debe dar una página vertical, y sólo esa."""
    doc = Documento()
    doc.agregar(imagen(tmp_path / "vertical.png", ROJO, tamano=(620, 876)))
    apaisada = doc.agregar(
        imagen(tmp_path / "apaisada.png", AZUL, tamano=(876, 620)))
    doc.rotar(apaisada.id, 90)

    destino = tmp_path / "rotada.pdf"
    assert ejecutar(app, doc.paginas, destino) == []

    pdf = pymupdf.open(destino)
    try:
        assert pdf.page_count == 2
        primera, segunda = pdf[0].rect, pdf[1].rect
        assert primera.height > primera.width, "la primera no se tocó"
        assert segunda.height > segunda.width, "tras rotar debería quedar vertical"
        assert parecido(color_dominante(pdf[1]), AZUL)
    finally:
        pdf.close()


def test_una_sola_pagina(app, tmp_path):
    doc = Documento()
    doc.agregar(imagen(tmp_path / "unica.png", VERDE))

    destino = tmp_path / "una.pdf"
    assert ejecutar(app, doc.paginas, destino) == []

    pdf = pymupdf.open(destino)
    try:
        assert pdf.page_count == 1
        assert parecido(color_dominante(pdf[0]), VERDE)
    finally:
        pdf.close()


def test_muchas_paginas_conservan_el_orden(app, tmp_path):
    """Con 12 páginas cualquier error de índice se hace visible."""
    doc = Documento()
    grises = [(20 * i + 20, 20 * i + 20, 20 * i + 20) for i in range(12)]
    for i, g in enumerate(grises):
        doc.agregar(imagen(tmp_path / f"g{i:02d}.png", g, tamano=(300, 420)))

    destino = tmp_path / "muchas.pdf"
    assert ejecutar(app, doc.paginas, destino) == []

    pdf = pymupdf.open(destino)
    try:
        assert pdf.page_count == 12
        for i, g in enumerate(grises):
            assert parecido(color_dominante(pdf[i]), g, tolerancia=18)
    finally:
        pdf.close()


# ── Errores ───────────────────────────────────────────────────────────────────

def test_falla_si_falta_una_imagen(app, tmp_path):
    """Mejor avisar que escribir un PDF al que le falta una hoja."""
    doc = Documento()
    doc.agregar(imagen(tmp_path / "existe.png", ROJO))
    doc.agregar(tmp_path / "no_existe.png")

    destino = tmp_path / "fallido.pdf"
    errores = ejecutar(app, doc.paginas, destino)

    assert errores, "debería reportar el error"
    assert not destino.exists(), "no debe quedar un PDF a medio escribir"


def test_sin_paginas_no_escribe_nada(app, tmp_path):
    destino = tmp_path / "vacio.pdf"
    errores = ejecutar(app, [], destino)
    assert errores
    assert not destino.exists()


def test_no_queda_basura_parcial_al_fallar(app, tmp_path):
    """El archivo .parcial de la escritura en dos pasos tiene que limpiarse."""
    doc = Documento()
    doc.agregar(tmp_path / "fantasma.png")

    destino = tmp_path / "salida.pdf"
    assert ejecutar(app, doc.paginas, destino)
    assert list(tmp_path.glob("*.parcial")) == []


def test_sobrescribir_un_pdf_existente(app, tmp_path):
    """Guardar sobre un archivo que ya estaba debe dejarlo íntegro."""
    destino = tmp_path / "existente.pdf"
    destino.write_bytes(b"contenido viejo que no es un PDF")

    doc = Documento()
    doc.agregar(imagen(tmp_path / "nueva.png", AZUL))

    assert ejecutar(app, doc.paginas, destino) == []

    pdf = pymupdf.open(destino)
    try:
        assert pdf.page_count == 1
        assert parecido(color_dominante(pdf[0]), AZUL)
    finally:
        pdf.close()
    assert list(tmp_path.glob("*.parcial")) == []
