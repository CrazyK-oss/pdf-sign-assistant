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
BLANCO = (250, 250, 248)   # el dorso de una hoja impresa de un solo lado


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


# ═══════════════════════════════════════════════════════════════════════════════
#  Partir de un PDF que ya existe
# ═══════════════════════════════════════════════════════════════════════════════

def pdf_con_texto(ruta: Path, textos) -> Path:
    doc = pymupdf.open()
    for t in textos:
        doc.new_page().insert_text((72, 120), t, fontsize=32)
    doc.save(ruta)
    doc.close()
    return ruta


def textos_de(ruta: Path) -> list[str]:
    doc = pymupdf.open(ruta)
    try:
        return [p.get_text().strip() for p in doc]
    finally:
        doc.close()


@pytest.fixture
def vista(app, tmp_path):
    from modules.herramienta_escaneo import VistaEscanearAPdf

    v = VistaEscanearAPdf(tmp_path / "salida")
    v.resize(1100, 720)
    yield v
    v.close()


def test_abrir_un_pdf_trae_sus_paginas(vista, tmp_path):
    """El caso que motivó todo: ya tenía el documento y me faltó una hoja."""
    from modules.documento import ORIGEN_PDF

    fuente = pdf_con_texto(tmp_path / "Contrato.pdf", ["UNO", "DOS"])
    vista._agregar([str(fuente)])

    assert vista.doc.total == 2
    assert all(p.origen == ORIGEN_PDF for p in vista.doc.paginas)
    assert vista.doc.nombre_sugerido() == "Contrato (editado).pdf"


def test_agregarle_una_hoja_escaneada_a_un_pdf(app, vista, tmp_path):
    """Lo importante: la hoja nueva se convierte, y las que ya eran PDF
    conservan su texto en vez de volver convertidas en fotos."""
    fuente = pdf_con_texto(tmp_path / "Contrato.pdf", ["UNO", "DOS"])
    vista._agregar([str(fuente)])

    hoja = imagen(tmp_path / "hoja.png", ROJO)
    vista._on_escaneo_listo(str(hoja))
    app.processEvents()
    assert vista.doc.total == 3
    assert vista.doc.mixto

    destino = tmp_path / "final.pdf"
    errores = ejecutar(app, list(vista.doc.paginas), destino)
    assert not errores, errores

    doc = pymupdf.open(destino)
    try:
        assert doc.page_count == 3
        assert [doc[i].get_text().strip() for i in (0, 1)] == ["UNO", "DOS"]
    finally:
        doc.close()
    assert parecido(color_dominante(pymupdf.open(destino)[2]), ROJO)


def test_el_pdf_que_se_abrio_no_es_temporal(vista, tmp_path):
    """Marcarlo temporal haría que la app borre el documento del usuario al
    cerrar la herramienta. Es el peor error posible de esta pantalla."""
    fuente = pdf_con_texto(tmp_path / "Contrato.pdf", ["UNO"])
    vista._agregar([str(fuente)])
    vista.limpiar_temporales()
    assert fuente.is_file()


def test_arrastrar_un_pdf_esta_permitido():
    from modules.documento import filtrar_soportados

    assert filtrar_soportados(["a.pdf", "b.png", "c.txt"]) == ["a.pdf", "b.png"]


# ═══════════════════════════════════════════════════════════════════════════════
#  Alimentador y dúplex
# ═══════════════════════════════════════════════════════════════════════════════

def vista_con_capacidades(app, tmp_path, cap, monkeypatch):
    """Una vista como si el escáner tuviera esas capacidades.

    Se parchea antes de construirla porque las capacidades se consultan
    una sola vez, al abrir la herramienta: preguntarle al escáner en cada
    refresco de pantalla lo despierta y tarda.
    """
    import modules.herramienta_escaneo as he

    monkeypatch.setattr(he, "capacidades_escaner", lambda: cap)
    monkeypatch.setattr(he, "verificar_escaneo_disponible", lambda: None)
    v = he.VistaEscanearAPdf(tmp_path / "salida")
    v.resize(1100, 720)
    app.processEvents()
    return v


def capacidades(**kw):
    from modules.dispositivos import CapacidadesEscaner

    base = dict(cristal=True, conocidas=True)
    base.update(kw)
    return CapacidadesEscaner(**base)


def test_un_escaner_de_cristal_no_ofrece_alimentador(app, tmp_path, monkeypatch):
    """Ofrecer "todo el alimentador" en una máquina que no lo tiene es un
    botón que devuelve error."""
    from modules.herramienta_escaneo import ORIGEN_CRISTAL

    v = vista_con_capacidades(app, tmp_path, capacidades(), monkeypatch)
    try:
        claves = [v.combo_origen.itemData(i)
                  for i in range(v.combo_origen.count())]
        assert claves == [ORIGEN_CRISTAL]
        assert v._origen == ORIGEN_CRISTAL
    finally:
        v.close()


def test_un_alimentador_simple_ofrece_lote_pero_no_duplex(app, tmp_path,
                                                          monkeypatch):
    from modules.herramienta_escaneo import ORIGEN_CRISTAL, ORIGEN_LOTE

    v = vista_con_capacidades(app, tmp_path, capacidades(alimentador=True),
                              monkeypatch)
    try:
        claves = [v.combo_origen.itemData(i)
                  for i in range(v.combo_origen.count())]
        assert claves == [ORIGEN_CRISTAL, ORIGEN_LOTE]
        assert v._origen == ORIGEN_LOTE, "con alimentador, es lo que conviene"
    finally:
        v.close()


def test_un_alimentador_duplex_ofrece_las_tres(app, tmp_path, monkeypatch):
    """La máquina que va a comprar el cliente."""
    from modules.herramienta_escaneo import (
        ORIGEN_CRISTAL,
        ORIGEN_LOTE,
        ORIGEN_LOTE_DUPLEX,
    )

    v = vista_con_capacidades(
        app, tmp_path, capacidades(alimentador=True, duplex=True), monkeypatch)
    try:
        claves = [v.combo_origen.itemData(i)
                  for i in range(v.combo_origen.count())]
        assert claves == [ORIGEN_CRISTAL, ORIGEN_LOTE, ORIGEN_LOTE_DUPLEX]
        assert v._origen == ORIGEN_LOTE_DUPLEX
    finally:
        v.close()


def test_un_driver_que_no_informa_nada_cae_a_cristal(app, tmp_path, monkeypatch):
    """Los drivers viejos no publican estas propiedades. Suponer que hay
    alimentador deja al usuario apretando un botón que da error."""
    from modules.herramienta_escaneo import ORIGEN_CRISTAL

    v = vista_con_capacidades(app, tmp_path, capacidades(conocidas=False),
                              monkeypatch)
    try:
        assert v._origen == ORIGEN_CRISTAL
        assert "no informa" in v.chip_escaner.toolTip()
    finally:
        v.close()


def test_el_chip_dice_que_tipo_de_escaner_hay(app, tmp_path, monkeypatch):
    v = vista_con_capacidades(
        app, tmp_path, capacidades(alimentador=True, duplex=True), monkeypatch)
    try:
        assert "Alimentador dúplex" in v.chip_escaner._texto.text()
    finally:
        v.close()


def test_las_paginas_del_lote_se_agregan_a_medida_que_llegan(app, tmp_path,
                                                             monkeypatch):
    """Con 30 hojas el lote son varios minutos: mostrarlas recién al final
    dejaría la pantalla muda todo ese rato."""
    v = vista_con_capacidades(app, tmp_path, capacidades(alimentador=True),
                              monkeypatch)
    try:
        for i in range(1, 4):
            v._on_pagina_del_lote(str(imagen(tmp_path / f"h{i}.png", ROJO)), i)
            app.processEvents()
            assert v.doc.total == i
            # Lo que de verdad importa: la fila ya está DIBUJADA. Mirar
            # sólo el modelo dejaría pasar que la lista se refresque
            # recién al terminar el taco, que es el defecto a evitar.
            assert len(v.panel._filas) == i, (
                f"llegó la página {i} y la lista muestra "
                f"{len(v.panel._filas)}")
        assert len(v._ids_del_lote) == 3
    finally:
        v.close()


def test_un_lote_interrumpido_conserva_lo_escaneado(app, tmp_path, monkeypatch):
    """Un atasco en la hoja 18 de 20 no puede tirar las 17 anteriores."""
    from modules.dispositivos import ErrorDispositivo

    v = vista_con_capacidades(app, tmp_path, capacidades(alimentador=True),
                              monkeypatch)
    avisos = []
    monkeypatch.setattr(
        "modules.herramienta_escaneo.QMessageBox.warning",
        lambda *a, **k: avisos.append(a))
    try:
        rutas = [str(imagen(tmp_path / f"h{i}.png", AZUL)) for i in range(3)]
        for i, r in enumerate(rutas, 1):
            v._on_pagina_del_lote(r, i)
        app.processEvents()

        v._on_lote_parcial(ErrorDispositivo("Se atascó el papel."), rutas)
        app.processEvents()

        assert v.doc.total == 3, "las páginas ya escaneadas se quedan"
        assert not v._escaneando
        assert avisos, "y el usuario tiene que enterarse del atasco"
    finally:
        v.close()


def test_en_duplex_se_ofrece_quitar_los_dorsos_en_blanco(app, tmp_path,
                                                         monkeypatch):
    """El problema clásico del dúplex: las hojas impresas de un solo lado
    dejan un dorso vacío en el medio del documento."""
    from PyQt6.QtWidgets import QMessageBox

    from modules.herramienta_escaneo import ORIGEN_LOTE_DUPLEX

    v = vista_con_capacidades(
        app, tmp_path, capacidades(alimentador=True, duplex=True), monkeypatch)
    preguntas = []
    monkeypatch.setattr(
        "modules.herramienta_escaneo.QMessageBox.question",
        lambda *a, **k: (preguntas.append(a),
                         QMessageBox.StandardButton.Yes)[1])
    try:
        assert v._origen == ORIGEN_LOTE_DUPLEX
        # frente con contenido, dorso vacío, frente con contenido, dorso vacío
        for i, color in enumerate([AZUL, BLANCO, ROJO, BLANCO], 1):
            v._on_pagina_del_lote(str(imagen(tmp_path / f"p{i}.png", color)), i)
        app.processEvents()
        assert v.doc.total == 4

        v._on_lote_completado(4)
        app.processEvents()

        assert preguntas, "tiene que preguntar antes de quitar nada"
        assert v.doc.total == 2, "quedan sólo los frentes"
    finally:
        v.close()


def test_los_dorsos_en_blanco_nunca_se_quitan_solos(app, tmp_path, monkeypatch):
    """Que sea una pregunta y no un automatismo es deliberado: la detección
    no distingue una página vacía de una que sólo tiene un folio."""
    from PyQt6.QtWidgets import QMessageBox

    v = vista_con_capacidades(
        app, tmp_path, capacidades(alimentador=True, duplex=True), monkeypatch)
    monkeypatch.setattr("modules.herramienta_escaneo.QMessageBox.question",
                        lambda *a, **k: QMessageBox.StandardButton.No)
    try:
        for i, color in enumerate([AZUL, BLANCO], 1):
            v._on_pagina_del_lote(str(imagen(tmp_path / f"p{i}.png", color)), i)
        v._on_lote_completado(2)
        app.processEvents()
        assert v.doc.total == 2, "diciendo que no, no se toca nada"
    finally:
        v.close()


def test_sin_duplex_no_se_pregunta_por_dorsos(app, tmp_path, monkeypatch):
    """En una sola cara no hay dorsos: una hoja en blanco en el taco es una
    hoja que el usuario puso a propósito."""
    v = vista_con_capacidades(app, tmp_path, capacidades(alimentador=True),
                              monkeypatch)
    preguntas = []
    monkeypatch.setattr("modules.herramienta_escaneo.QMessageBox.question",
                        lambda *a, **k: preguntas.append(a))
    try:
        v._on_pagina_del_lote(str(imagen(tmp_path / "v.png", BLANCO)), 1)
        v._on_lote_completado(1)
        app.processEvents()
        assert not preguntas
        assert v.doc.total == 1
    finally:
        v.close()
