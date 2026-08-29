"""
tests/test_integracion_unir.py
============================================================
Tests de la herramienta "Unir y dividir PDFs".

Lo que se cubre acá es lo que la pantalla decide, no lo que el motor
escribe —eso ya lo prueba tests/test_armado_pdf.py abriendo el PDF
resultante—: qué páginas entran al agregar archivos, en qué orden quedan,
y sobre todo qué grupos arma el diálogo de dividir para cada modo. Ese
diálogo es el único lugar donde un error de índice se convierte
directamente en archivos con las páginas equivocadas.

Los diálogos modales no se abren con exec(): se les fija el estado y se
les pregunta el resultado. Un exec() en un test cuelga la suite.

Necesitan PyQt6 y PyMuPDF, así que llevan la marca `integracion`.
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

from modules.documento import ORIGEN_IMAGEN, ORIGEN_PDF  # noqa: E402
from modules.herramienta_unir import (  # noqa: E402
    DialogoDividir,
    VistaUnirDividirPdf,
    _WorkerDividir,
    _WorkerUnir,
)

pytestmark = pytest.mark.integracion

TIMEOUT = 90


@pytest.fixture(scope="module")
def app(qapp):
    from modules.theme import apply_theme

    apply_theme(qapp, "light")
    return qapp


def pdf(ruta: Path, textos) -> Path:
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
    v = VistaUnirDividirPdf(tmp_path / "salida")
    v.resize(1100, 720)
    yield v
    v.close()


@pytest.fixture
def contrato(tmp_path) -> Path:
    return pdf(tmp_path / "Contrato.pdf", ["UNO", "DOS", "TRES"])


@pytest.fixture
def anexo(tmp_path) -> Path:
    return pdf(tmp_path / "Anexo.pdf", ["ANEXO"])


def esperar(app, worker) -> None:
    """Espera al hilo procesando eventos.

    El processEvents() no es decorativo: las señales que cruzan de hilo
    llegan por la cola de eventos del receptor, así que un sleep() a secas
    deja `listo` sin entregar y el test ve una lista vacía.
    """
    limite = time.time() + TIMEOUT
    while worker.isRunning() and time.time() < limite:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()          # las últimas señales, ya terminado el hilo
    assert not worker.isRunning(), "el worker no terminó a tiempo"


# ═══════════════════════════════════════════════════════════════════════════════
#  Agregar archivos
# ═══════════════════════════════════════════════════════════════════════════════

def test_agregar_un_pdf_trae_todas_sus_paginas(vista, contrato):
    vista._agregar([str(contrato)])
    assert vista.doc.total == 3
    assert all(p.origen == ORIGEN_PDF for p in vista.doc.paginas)
    assert [p.indice for p in vista.doc.paginas] == [0, 1, 2]


def test_agregar_dos_pdf_los_concatena_en_orden(vista, contrato, anexo):
    vista._agregar([str(contrato), str(anexo)])
    assert vista.doc.total == 4
    assert vista.doc.paginas[3].nombre == "Anexo.pdf"


def test_el_nombre_sugerido_sale_del_primero(vista, contrato, anexo):
    """Guardar como "Anexo (editado)" un documento que arranca con el
    contrato desconcertaría."""
    vista._agregar([str(contrato), str(anexo)])
    assert vista.doc.nombre_sugerido() == "Contrato (editado).pdf"


def test_se_pueden_mezclar_imagenes(vista, contrato, tmp_path):
    hoja = tmp_path / "hoja.png"
    Image.new("RGB", (600, 850), (240, 240, 240)).save(hoja)

    vista._agregar([str(contrato), str(hoja)])
    assert vista.doc.total == 4
    assert vista.doc.paginas[-1].origen == ORIGEN_IMAGEN
    assert vista.doc.mixto


def test_un_pdf_ilegible_no_tumba_a_los_demas(vista, contrato, tmp_path,
                                              monkeypatch):
    """Arrastrar una carpeta entera puede traer un archivo roto: los que
    sí se pueden abrir tienen que entrar igual."""
    roto = tmp_path / "roto.pdf"
    roto.write_bytes(b"esto no es un PDF")

    avisos = []
    monkeypatch.setattr("modules.herramienta_unir.QMessageBox.warning",
                        lambda *a, **k: avisos.append(a))

    vista._agregar([str(contrato), str(roto)])
    assert vista.doc.total == 3, "las páginas del contrato tienen que estar"
    assert avisos, "y el usuario tiene que enterarse del que falló"


def test_agregar_algo_que_no_se_puede_abrir(vista, tmp_path, monkeypatch):
    basura = tmp_path / "notas.txt"
    basura.write_text("hola")

    avisados = []
    monkeypatch.setattr("modules.herramienta_unir.QMessageBox.information",
                        lambda *a, **k: avisados.append(a))

    vista._agregar([str(basura)])
    assert vista.doc.vacio
    assert avisados


# ═══════════════════════════════════════════════════════════════════════════════
#  Estado de la pantalla
# ═══════════════════════════════════════════════════════════════════════════════

def test_al_empezar_no_se_puede_guardar_ni_dividir(vista, app):
    app.processEvents()
    assert not vista.btn_guardar.isEnabled()
    assert not vista.btn_dividir.isEnabled()


def test_con_una_sola_pagina_se_guarda_pero_no_se_divide(vista, app, anexo):
    """Partir un documento de una página en varios archivos no significa
    nada, y el botón encendido invita a intentarlo."""
    vista._agregar([str(anexo)])
    app.processEvents()
    assert vista.btn_guardar.isEnabled()
    assert not vista.btn_dividir.isEnabled()


def test_con_varias_paginas_se_habilita_todo(vista, app, contrato):
    vista._agregar([str(contrato)])
    app.processEvents()
    assert vista.btn_guardar.isEnabled()
    assert vista.btn_dividir.isEnabled()


def test_el_chip_cuenta_los_archivos_de_origen(vista, app, contrato, anexo):
    vista._agregar([str(contrato), str(anexo)])
    app.processEvents()
    assert "2 PDF" in vista.chip_archivos._texto.text()


def test_quitar_una_pagina_desde_la_lista(vista, app, contrato):
    vista._agregar([str(contrato)])
    app.processEvents()
    vista.panel.quitar(vista.doc.paginas[1].id)
    app.processEvents()
    assert [p.indice for p in vista.doc.paginas] == [0, 2]


def test_reordenar_desde_la_lista(vista, app, contrato):
    vista._agregar([str(contrato)])
    app.processEvents()
    ultima = vista.doc.paginas[2].id
    vista.panel.mover(ultima, -1)
    app.processEvents()
    assert [p.indice for p in vista.doc.paginas] == [0, 2, 1]


# ═══════════════════════════════════════════════════════════════════════════════
#  Diálogo de dividir
# ═══════════════════════════════════════════════════════════════════════════════

def test_dividir_una_por_pagina(app):
    d = DialogoDividir(4)
    d.rb_una.setChecked(True)
    assert d.grupos() == [[0], [1], [2], [3]]


def test_dividir_cada_n_paginas(app):
    d = DialogoDividir(7)
    d.rb_cada.setChecked(True)
    d.spin.setValue(3)
    assert d.grupos() == [[0, 1, 2], [3, 4, 5], [6]]


def test_dividir_cada_n_no_inventa_paginas_en_el_ultimo(app):
    """7 de a 3 son 3+3+1, no 3+3+3."""
    d = DialogoDividir(7)
    d.rb_cada.setChecked(True)
    d.spin.setValue(3)
    assert sum(len(g) for g in d.grupos()) == 7


def test_dividir_por_rangos(app):
    d = DialogoDividir(9)
    d.rb_rangos.setChecked(True)
    d.campo.setText("1-3, 7-9")
    assert d.grupos() == [[0, 1, 2], [6, 7, 8]]


def test_un_rango_ilegible_apaga_el_boton_y_lo_explica(app):
    d = DialogoDividir(5)
    d.rb_rangos.setChecked(True)
    d.campo.setText("1-99")

    ok = d.botones.button(d.botones.StandardButton.Ok)
    assert not ok.isEnabled()
    assert "99" in d.aviso._texto.text()
    assert d.campo.property("invalid") == "true"


def test_al_corregir_el_rango_vuelve_a_habilitarse(app):
    d = DialogoDividir(5)
    d.rb_rangos.setChecked(True)
    d.campo.setText("1-99")
    d.campo.setText("1-2")

    ok = d.botones.button(d.botones.StandardButton.Ok)
    assert ok.isEnabled()
    assert d.campo.property("invalid") == "false"
    assert d.aviso.isHidden()


def test_el_resumen_dice_cuantos_archivos_van_a_salir(app):
    d = DialogoDividir(9)
    d.rb_rangos.setChecked(True)
    d.campo.setText("1-3, 7-9")
    assert "2 archivos" in d.resumen.text()
    assert "1-3" in d.resumen.text() and "7-9" in d.resumen.text()


def test_cambiar_de_modo_apaga_los_controles_del_otro(app):
    d = DialogoDividir(5)
    d.rb_una.setChecked(True)
    assert not d.campo.isEnabled() and not d.spin.isEnabled()

    d.rb_cada.setChecked(True)
    assert d.spin.isEnabled() and not d.campo.isEnabled()

    d.rb_rangos.setChecked(True)
    assert d.campo.isEnabled() and not d.spin.isEnabled()


def test_un_rango_vacio_no_deja_dividir(app):
    d = DialogoDividir(5)
    d.rb_rangos.setChecked(True)
    d.campo.setText("")
    assert not d.botones.button(d.botones.StandardButton.Ok).isEnabled()


def test_un_documento_de_una_pagina_no_rompe_el_spin(app):
    """El rango del spin arranca en 1: con total=1 no puede quedar vacío."""
    d = DialogoDividir(1)
    d.rb_cada.setChecked(True)
    assert d.spin.value() >= 1
    assert d.grupos() == [[0]]


# ═══════════════════════════════════════════════════════════════════════════════
#  De punta a punta
# ═══════════════════════════════════════════════════════════════════════════════

def test_unir_dos_pdf_de_punta_a_punta(vista, app, contrato, anexo, tmp_path):
    vista._agregar([str(contrato), str(anexo)])
    app.processEvents()

    destino = tmp_path / "unido.pdf"
    worker = _WorkerUnir(list(vista.doc.paginas), destino)
    errores = []
    worker.error.connect(errores.append)
    worker.start()
    esperar(app, worker)

    assert not errores, errores
    assert textos_de(destino) == ["UNO", "DOS", "TRES", "ANEXO"]


def test_reordenar_antes_de_unir_se_respeta(vista, app, contrato, tmp_path):
    vista._agregar([str(contrato)])
    app.processEvents()
    vista._invertir()
    app.processEvents()

    destino = tmp_path / "invertido.pdf"
    worker = _WorkerUnir(list(vista.doc.paginas), destino)
    worker.start()
    esperar(app, worker)

    assert textos_de(destino) == ["TRES", "DOS", "UNO"]


def test_dividir_de_punta_a_punta(vista, app, contrato, tmp_path):
    vista._agregar([str(contrato)])
    app.processEvents()

    d = DialogoDividir(vista.doc.total)
    d.rb_una.setChecked(True)
    trozos = vista.doc.partir_en(d.grupos())

    carpeta = tmp_path / "partes"
    carpeta.mkdir()
    trabajos = [(list(t.paginas), carpeta / t.nombre_de_trozo(i, len(trozos)))
                for i, t in enumerate(trozos, 1)]

    worker = _WorkerDividir(trabajos)
    rutas, errores = [], []
    worker.listo.connect(rutas.extend)
    worker.error.connect(errores.append)
    worker.start()
    esperar(app, worker)

    assert not errores, errores
    assert len(rutas) == 3
    assert [textos_de(Path(r)) for r in rutas] == [["UNO"], ["DOS"], ["TRES"]]
    assert [Path(r).name for r in rutas] == [
        "Contrato (parte 1 de 3).pdf",
        "Contrato (parte 2 de 3).pdf",
        "Contrato (parte 3 de 3).pdf"]


def test_dividir_por_rangos_de_punta_a_punta(vista, app, contrato, tmp_path):
    vista._agregar([str(contrato)])
    app.processEvents()

    d = DialogoDividir(vista.doc.total)
    d.rb_rangos.setChecked(True)
    d.campo.setText("1-2, 3")
    trozos = vista.doc.partir_en(d.grupos())

    carpeta = tmp_path / "partes"
    carpeta.mkdir()
    trabajos = [(list(t.paginas), carpeta / f"p{i}.pdf")
                for i, t in enumerate(trozos, 1)]

    worker = _WorkerDividir(trabajos)
    rutas = []
    worker.listo.connect(rutas.extend)
    worker.start()
    esperar(app, worker)

    assert [textos_de(Path(r)) for r in rutas] == [["UNO", "DOS"], ["TRES"]]


def test_dividir_no_toca_el_pdf_de_origen(vista, app, contrato, tmp_path):
    antes = contrato.read_bytes()
    vista._agregar([str(contrato)])
    app.processEvents()

    carpeta = tmp_path / "partes"
    carpeta.mkdir()
    trozos = vista.doc.partir_cada(1)
    worker = _WorkerDividir([(list(t.paginas), carpeta / f"p{i}.pdf")
                             for i, t in enumerate(trozos, 1)])
    worker.start()
    esperar(app, worker)

    assert contrato.read_bytes() == antes


# ═══════════════════════════════════════════════════════════════════════════════
#  Arrastrar y soltar
# ═══════════════════════════════════════════════════════════════════════════════

def test_el_filtro_de_arrastre_acepta_pdf_e_imagenes():
    from modules.documento import filtrar_soportados

    sueltos = ["a.pdf", "b.png", "notas.txt", "c.jpg", "d.docx"]
    assert filtrar_soportados(sueltos) == ["a.pdf", "b.png", "c.jpg"]


def test_vaciar_la_lista(vista, app, contrato, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    vista._agregar([str(contrato)])
    app.processEvents()
    monkeypatch.setattr("modules.herramienta_unir.QMessageBox.question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    vista._vaciar()
    app.processEvents()
    assert vista.doc.vacio
    assert contrato.is_file(), "vaciar la lista no borra los archivos del usuario"
