"""
tests/test_armado_pdf.py
============================================================
Tests del motor que escribe el PDF final.

El más importante del archivo es
`test_una_pagina_de_pdf_conserva_su_texto`. Es la regla que justifica que
el armado tenga dos caminos: una página que ya es PDF se **copia**, nunca
se rasteriza. Si alguien "simplificara" el motor pasando todo por el
convertidor de imágenes, un contrato con texto seleccionable volvería
convertido en fotos —sin búsqueda, sin copiar y pegar, ilegible para un
lector de pantalla y diez veces más pesado— y ningún test de cantidad de
páginas lo notaría. Este sí.

No usan Qt: el motor es Python puro y se prueba abriendo el PDF que
escribió. Necesitan pypdf y PyMuPDF, así que llevan la marca `integracion`
y se saltean solos en el CI liviano.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pypdf", reason="Necesita pypdf")
pytest.importorskip("pymupdf", reason="Necesita PyMuPDF")
pytest.importorskip("PIL", reason="Necesita Pillow")

import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from modules.armado_pdf import (  # noqa: E402
    ErrorArmado,
    PaginaPlana,
    abrir_en,
    armar_pdf,
    armar_varios,
    contar_paginas,
    instantanea,
)
from modules.documento import ORIGEN_ESCANER, ORIGEN_PDF, Documento  # noqa: E402

pytestmark = pytest.mark.integracion

ROJO = (220, 60, 60)
AZUL = (60, 140, 220)


# ── Material de prueba ────────────────────────────────────────────────────────

def pdf_con_texto(ruta: Path, textos, rotaciones=None) -> Path:
    """Un PDF con una página por texto, con texto de verdad (no dibujado)."""
    giros = list(rotaciones or ())
    doc = pymupdf.open()
    for i, t in enumerate(textos):
        pagina = doc.new_page()
        pagina.insert_text((72, 120), t, fontsize=36)
        if i < len(giros) and giros[i]:
            pagina.set_rotation(giros[i])
    doc.save(ruta)
    doc.close()
    return ruta


def imagen(ruta: Path, color) -> Path:
    Image.new("RGB", (620, 876), color).save(ruta, dpi=(150, 150))
    return ruta


def textos_de(ruta: Path) -> list[str]:
    doc = pymupdf.open(ruta)
    try:
        return [p.get_text().strip() for p in doc]
    finally:
        doc.close()


def rotaciones_de(ruta: Path) -> list[int]:
    return [int(p.get("/Rotate", 0)) for p in PdfReader(str(ruta)).pages]


def color_dominante(ruta: Path, indice: int) -> tuple[int, int, int]:
    doc = pymupdf.open(ruta)
    try:
        pix = doc[indice].get_pixmap(dpi=36)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return max(img.getcolors(img.width * img.height))[1]
    finally:
        doc.close()


def parecido(a, b, tolerancia=42) -> bool:
    return all(abs(x - y) <= tolerancia for x, y in zip(a, b))


@pytest.fixture
def fuente(tmp_path) -> Path:
    """Un PDF de 3 páginas con los textos UNO, DOS y TRES."""
    return pdf_con_texto(tmp_path / "fuente.pdf", ["UNO", "DOS", "TRES"])


def paginas_pdf(ruta: Path, indices, rotacion=0):
    return [PaginaPlana(ruta, rotacion, ORIGEN_PDF, i) for i in indices]


# ═══════════════════════════════════════════════════════════════════════════════
#  Lo que no se puede perder: el texto
# ═══════════════════════════════════════════════════════════════════════════════

def test_una_pagina_de_pdf_conserva_su_texto(fuente, tmp_path):
    """La razón de ser de todo el módulo.

    Si el motor rasterizara las páginas de PDF, esto seguiría dando 1
    página y saldría en verde cualquier test que sólo cuente páginas. Acá
    se le pide el texto al resultado: una foto no tiene.
    """
    salida = armar_pdf(paginas_pdf(fuente, [1]), tmp_path / "salida.pdf")
    assert textos_de(salida) == ["DOS"]


def test_copiar_un_pdf_entero_conserva_todo_el_texto(fuente, tmp_path):
    salida = armar_pdf(paginas_pdf(fuente, [0, 1, 2]), tmp_path / "salida.pdf")
    assert textos_de(salida) == ["UNO", "DOS", "TRES"]


def test_el_pdf_de_origen_no_se_toca(fuente, tmp_path):
    """El usuario abrió SU archivo: el motor no puede modificarlo."""
    antes = fuente.read_bytes()
    armar_pdf(paginas_pdf(fuente, [2, 0]), tmp_path / "salida.pdf")
    assert fuente.read_bytes() == antes


def test_reordenar_paginas_de_pdf(fuente, tmp_path):
    salida = armar_pdf(paginas_pdf(fuente, [2, 0, 1]), tmp_path / "salida.pdf")
    assert textos_de(salida) == ["TRES", "UNO", "DOS"]


def test_quitar_paginas(fuente, tmp_path):
    salida = armar_pdf(paginas_pdf(fuente, [0, 2]), tmp_path / "salida.pdf")
    assert textos_de(salida) == ["UNO", "TRES"]


def test_una_pagina_puede_repetirse(fuente, tmp_path):
    """Un rango escrito a mano puede pedir la misma página dos veces; el
    motor no tiene por qué opinar."""
    salida = armar_pdf(paginas_pdf(fuente, [1, 1]), tmp_path / "salida.pdf")
    assert textos_de(salida) == ["DOS", "DOS"]


def test_unir_dos_pdf_distintos(tmp_path):
    a = pdf_con_texto(tmp_path / "a.pdf", ["A1", "A2"])
    b = pdf_con_texto(tmp_path / "b.pdf", ["B1"])
    paginas = paginas_pdf(a, [0, 1]) + paginas_pdf(b, [0])
    salida = armar_pdf(paginas, tmp_path / "unido.pdf")
    assert textos_de(salida) == ["A1", "A2", "B1"]


def test_intercalar_paginas_de_dos_pdf(tmp_path):
    """Cada archivo se abre una sola vez aunque sus páginas estén salteadas."""
    a = pdf_con_texto(tmp_path / "a.pdf", ["A1", "A2"])
    b = pdf_con_texto(tmp_path / "b.pdf", ["B1", "B2"])
    paginas = [PaginaPlana(a, 0, ORIGEN_PDF, 0), PaginaPlana(b, 0, ORIGEN_PDF, 0),
               PaginaPlana(a, 0, ORIGEN_PDF, 1), PaginaPlana(b, 0, ORIGEN_PDF, 1)]
    salida = armar_pdf(paginas, tmp_path / "salida.pdf")
    assert textos_de(salida) == ["A1", "B1", "A2", "B2"]


# ═══════════════════════════════════════════════════════════════════════════════
#  Orígenes mezclados
# ═══════════════════════════════════════════════════════════════════════════════

def test_pdf_e_imagen_en_el_mismo_documento(fuente, tmp_path):
    """El caso de "escaneé una hoja más y la agrego al contrato": la página
    escaneada se convierte, y las que ya eran PDF siguen con su texto."""
    hoja = imagen(tmp_path / "hoja.png", ROJO)
    paginas = paginas_pdf(fuente, [0]) + [PaginaPlana(hoja, 0, ORIGEN_ESCANER, 0)]

    salida = armar_pdf(paginas, tmp_path / "salida.pdf")

    assert len(PdfReader(str(salida)).pages) == 2
    assert textos_de(salida)[0] == "UNO"
    assert parecido(color_dominante(salida, 1), ROJO)


def test_una_imagen_intercalada_no_desordena_el_resto(fuente, tmp_path):
    hoja = imagen(tmp_path / "hoja.png", AZUL)
    paginas = [PaginaPlana(fuente, 0, ORIGEN_PDF, 0),
               PaginaPlana(hoja, 0, ORIGEN_ESCANER, 0),
               PaginaPlana(fuente, 0, ORIGEN_PDF, 1)]

    salida = armar_pdf(paginas, tmp_path / "salida.pdf")

    textos = textos_de(salida)
    assert textos[0] == "UNO" and textos[2] == "DOS"
    assert parecido(color_dominante(salida, 1), AZUL)


def test_solo_imagenes_sigue_andando(tmp_path):
    """El camino viejo, el de "Escanear a PDF", no se rompió."""
    a = imagen(tmp_path / "a.png", ROJO)
    b = imagen(tmp_path / "b.png", AZUL)
    paginas = [PaginaPlana(a, 0, ORIGEN_ESCANER, 0),
               PaginaPlana(b, 0, ORIGEN_ESCANER, 0)]

    salida = armar_pdf(paginas, tmp_path / "salida.pdf")

    assert parecido(color_dominante(salida, 0), ROJO)
    assert parecido(color_dominante(salida, 1), AZUL)


# ═══════════════════════════════════════════════════════════════════════════════
#  Rotación
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_rotacion_se_le_aplica_a_la_pagina_pedida(fuente, tmp_path):
    paginas = [PaginaPlana(fuente, 0, ORIGEN_PDF, 0),
               PaginaPlana(fuente, 90, ORIGEN_PDF, 1),
               PaginaPlana(fuente, 0, ORIGEN_PDF, 2)]
    salida = armar_pdf(paginas, tmp_path / "salida.pdf")
    assert rotaciones_de(salida) == [0, 90, 0]


def test_la_rotacion_se_suma_a_la_que_el_pdf_ya_traia(tmp_path):
    """`rotacion` es un giro EXTRA. Una página guardada a 90° que el
    usuario gira otros 90 tiene que quedar a 180, no volver a 90."""
    fuente = pdf_con_texto(tmp_path / "f.pdf", ["A", "B"], rotaciones=[90, 0])
    assert rotaciones_de(fuente) == [90, 0]

    paginas = [PaginaPlana(fuente, 90, ORIGEN_PDF, 0),
               PaginaPlana(fuente, 90, ORIGEN_PDF, 1)]
    salida = armar_pdf(paginas, tmp_path / "salida.pdf")
    assert rotaciones_de(salida) == [180, 90]


def test_la_misma_pagina_con_dos_rotaciones_distintas(fuente, tmp_path):
    """Girar la copia del escritor y no la del lector: si se mutara el
    original, las dos entradas terminarían con la última rotación."""
    paginas = [PaginaPlana(fuente, 0, ORIGEN_PDF, 0),
               PaginaPlana(fuente, 90, ORIGEN_PDF, 0),
               PaginaPlana(fuente, 180, ORIGEN_PDF, 0)]
    salida = armar_pdf(paginas, tmp_path / "salida.pdf")
    assert rotaciones_de(salida) == [0, 90, 180]


def test_girar_una_pagina_de_pdf_no_le_saca_el_texto(fuente, tmp_path):
    """Rotar por /Rotate es sin pérdida; rasterizar para girar no lo sería."""
    salida = armar_pdf([PaginaPlana(fuente, 90, ORIGEN_PDF, 0)],
                       tmp_path / "salida.pdf")
    assert textos_de(salida) == ["UNO"]


def test_girar_una_imagen(tmp_path):
    hoja = imagen(tmp_path / "hoja.png", ROJO)
    salida = armar_pdf([PaginaPlana(hoja, 90, ORIGEN_ESCANER, 0)],
                       tmp_path / "salida.pdf")
    assert rotaciones_de(salida) == [90]
    assert parecido(color_dominante(salida, 0), ROJO)


# ═══════════════════════════════════════════════════════════════════════════════
#  Errores y seguridad del archivo
# ═══════════════════════════════════════════════════════════════════════════════

def test_sin_paginas_no_escribe_nada(tmp_path):
    destino = tmp_path / "salida.pdf"
    with pytest.raises(ErrorArmado, match="No hay páginas"):
        armar_pdf([], destino)
    assert not destino.exists()


def test_un_archivo_que_falta_dice_que_pagina_es(fuente, tmp_path):
    paginas = paginas_pdf(fuente, [0]) + [
        PaginaPlana(tmp_path / "fantasma.png", 0, ORIGEN_ESCANER, 0)]
    with pytest.raises(ErrorArmado, match="página 2"):
        armar_pdf(paginas, tmp_path / "salida.pdf")


def test_una_pagina_que_ya_no_existe_en_el_pdf(fuente, tmp_path):
    """El usuario puede haber editado el archivo por fuera entre que lo
    abrió y que apretó Guardar."""
    with pytest.raises(ErrorArmado, match="ahora tiene 3"):
        armar_pdf(paginas_pdf(fuente, [9]), tmp_path / "salida.pdf")


def test_al_fallar_no_queda_un_parcial(fuente, tmp_path):
    paginas = paginas_pdf(fuente, [0]) + [
        PaginaPlana(tmp_path / "fantasma.png", 0, ORIGEN_ESCANER, 0)]
    with pytest.raises(ErrorArmado):
        armar_pdf(paginas, tmp_path / "salida.pdf")
    assert list(tmp_path.glob("*.parcial")) == []


def test_al_fallar_no_se_pisa_el_archivo_que_ya_estaba(fuente, tmp_path):
    """Escribir a un temporal y renombrar existe justo para esto: un error
    a mitad de camino no puede dejar truncado lo que el usuario tenía."""
    destino = pdf_con_texto(tmp_path / "salida.pdf", ["ORIGINAL"])
    antes = destino.read_bytes()

    paginas = paginas_pdf(fuente, [0]) + [
        PaginaPlana(tmp_path / "fantasma.png", 0, ORIGEN_ESCANER, 0)]
    with pytest.raises(ErrorArmado):
        armar_pdf(paginas, destino)

    assert destino.read_bytes() == antes
    assert textos_de(destino) == ["ORIGINAL"]


def test_sobrescribir_a_proposito_si_funciona(fuente, tmp_path):
    destino = pdf_con_texto(tmp_path / "salida.pdf", ["VIEJO"])
    armar_pdf(paginas_pdf(fuente, [0]), destino)
    assert textos_de(destino) == ["UNO"]


def test_se_crea_la_carpeta_de_destino(fuente, tmp_path):
    destino = tmp_path / "sub" / "carpeta" / "salida.pdf"
    armar_pdf(paginas_pdf(fuente, [0]), destino)
    assert destino.is_file()


def test_cancelar_corta_sin_dejar_archivo(fuente, tmp_path):
    destino = tmp_path / "salida.pdf"
    with pytest.raises(ErrorArmado, match="Cancelado"):
        armar_pdf(paginas_pdf(fuente, [0, 1, 2]), destino,
                  cancelado=lambda: True)
    assert not destino.exists()


def test_el_progreso_avanza_y_termina_en_cien(fuente, tmp_path):
    visto: list[int] = []
    armar_pdf(paginas_pdf(fuente, [0, 1, 2]), tmp_path / "salida.pdf",
              progreso=lambda pct, _texto: visto.append(pct))
    assert visto == sorted(visto), f"el progreso retrocedió: {visto}"
    assert visto[-1] == 100


def test_el_documento_lleva_la_firma_de_la_app(fuente, tmp_path):
    salida = armar_pdf(paginas_pdf(fuente, [0]), tmp_path / "salida.pdf")
    meta = PdfReader(str(salida)).metadata or {}
    assert "PDF Sign Assistant" in str(meta.get("/Producer", ""))


# ═══════════════════════════════════════════════════════════════════════════════
#  Lectura: contar_paginas y abrir_en
# ═══════════════════════════════════════════════════════════════════════════════

def test_contar_paginas(fuente):
    assert contar_paginas(fuente) == 3


def test_contar_paginas_de_algo_que_no_esta(tmp_path):
    with pytest.raises(ErrorArmado, match="No se encuentra"):
        contar_paginas(tmp_path / "nada.pdf")


def test_contar_paginas_de_algo_que_no_es_pdf(tmp_path):
    falso = tmp_path / "falso.pdf"
    falso.write_bytes(b"esto no es un PDF")
    with pytest.raises(ErrorArmado, match="dañado o no ser un PDF"):
        contar_paginas(falso)


def test_un_pdf_con_contrasena_lo_dice_claro(tmp_path):
    protegido = tmp_path / "protegido.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 120), "SECRETO", fontsize=36)
    doc.save(protegido, encryption=pymupdf.PDF_ENCRYPT_AES_256,
             user_pw="clave", owner_pw="clave")
    doc.close()

    with pytest.raises(ErrorArmado, match="contraseña"):
        contar_paginas(protegido)


def test_abrir_en_suma_las_paginas_y_deja_el_nombre_base(fuente):
    doc = Documento()
    assert abrir_en(doc, fuente) == 3
    assert doc.total == 3
    assert all(p.origen == ORIGEN_PDF for p in doc.paginas)
    assert doc.base_nombre == "fuente"
    assert doc.nombre_sugerido() == "fuente (editado).pdf"


def test_abrir_un_segundo_pdf_no_le_cambia_el_nombre_base(fuente, tmp_path):
    """El nombre sugerido sale del primero que se abrió; ir agregando
    archivos no debería andar cambiándolo por debajo."""
    otro = pdf_con_texto(tmp_path / "otro.pdf", ["X"])
    doc = Documento()
    abrir_en(doc, fuente)
    abrir_en(doc, otro)
    assert doc.base_nombre == "fuente"
    assert doc.total == 4


def test_abrir_en_una_posicion(fuente, tmp_path):
    otro = pdf_con_texto(tmp_path / "otro.pdf", ["X", "Y"])
    doc = Documento()
    abrir_en(doc, fuente)
    abrir_en(doc, otro, indice=1)

    salida = armar_pdf(instantanea(doc.paginas), tmp_path / "salida.pdf")
    assert textos_de(salida) == ["UNO", "X", "Y", "DOS", "TRES"]


# ═══════════════════════════════════════════════════════════════════════════════
#  De punta a punta, con el modelo
# ═══════════════════════════════════════════════════════════════════════════════

def test_el_documento_completo_se_arma_como_quedo_en_pantalla(fuente, tmp_path):
    """Abrir un PDF, agregar una hoja escaneada, reordenar y girar."""
    hoja = imagen(tmp_path / "hoja.png", AZUL)
    doc = Documento()
    abrir_en(doc, fuente)
    nueva = doc.agregar(hoja, origen=ORIGEN_ESCANER, temporal=True)

    doc.mover_a(nueva.id, 0)              # la escaneada va primero
    doc.rotar(doc.paginas[1].id, 90)      # y "UNO" queda de costado

    salida = armar_pdf(instantanea(doc.paginas), tmp_path / "salida.pdf")

    assert parecido(color_dominante(salida, 0), AZUL)
    assert textos_de(salida)[1:] == ["UNO", "DOS", "TRES"]
    assert rotaciones_de(salida) == [0, 90, 0, 0]


def test_la_instantanea_congela_la_lista(fuente, tmp_path):
    """El usuario puede seguir tocando la pantalla mientras el hilo
    escribe: lo que se guarda es lo que había al apretar Guardar."""
    doc = Documento()
    abrir_en(doc, fuente)
    congelada = instantanea(doc.paginas)

    doc.invertir()
    doc.quitar(doc.paginas[0].id)

    salida = armar_pdf(congelada, tmp_path / "salida.pdf")
    assert textos_de(salida) == ["UNO", "DOS", "TRES"]


def test_dividir_y_volver_a_unir_da_lo_mismo(fuente, tmp_path):
    """Partir en trozos y pegarlos de nuevo tiene que devolver el original.
    Es la prueba de que `subconjunto` no pierde ni reordena nada."""
    doc = Documento()
    abrir_en(doc, fuente)

    trozos = doc.partir_cada(2)
    assert [t.total for t in trozos] == [2, 1]

    paginas = [p for t in trozos for p in instantanea(t.paginas)]
    salida = armar_pdf(paginas, tmp_path / "rearmado.pdf")
    assert textos_de(salida) == ["UNO", "DOS", "TRES"]


# ═══════════════════════════════════════════════════════════════════════════════
#  Varios archivos de una (dividir)
# ═══════════════════════════════════════════════════════════════════════════════

def test_armar_varios_escribe_todos(fuente, tmp_path):
    doc = Documento()
    abrir_en(doc, fuente)
    trozos = doc.partir_cada(1)

    trabajos = [(instantanea(t.paginas), tmp_path / f"parte{i}.pdf")
                for i, t in enumerate(trozos, 1)]
    hechos = armar_varios(trabajos)

    assert [r.name for r in hechos] == ["parte1.pdf", "parte2.pdf", "parte3.pdf"]
    assert [textos_de(r) for r in hechos] == [["UNO"], ["DOS"], ["TRES"]]


def test_armar_varios_avanza_de_cero_a_cien_una_sola_vez(fuente, tmp_path):
    """El progreso se reparte entre los archivos: si cada uno avanzara de
    0 a 100, la barra daría tres vueltas y no diría nada útil."""
    doc = Documento()
    abrir_en(doc, fuente)
    trabajos = [(instantanea(t.paginas), tmp_path / f"p{i}.pdf")
                for i, t in enumerate(doc.partir_cada(1), 1)]

    visto: list[int] = []
    armar_varios(trabajos, progreso=lambda pct, _t: visto.append(pct))

    assert visto == sorted(visto), f"el progreso retrocedió: {visto}"
    assert visto[-1] == 100
    assert max(visto) <= 100


def test_armar_varios_conserva_lo_que_ya_habia_escrito(fuente, tmp_path):
    """Si el tercero falla, los dos primeros son archivos válidos: borrarlos
    sería tirar trabajo bueno por un error posterior."""
    doc = Documento()
    abrir_en(doc, fuente)
    buenos = [(instantanea(t.paginas), tmp_path / f"p{i}.pdf")
              for i, t in enumerate(doc.partir_cada(1), 1)]
    roto = ([PaginaPlana(tmp_path / "fantasma.png", 0, ORIGEN_ESCANER, 0)],
            tmp_path / "roto.pdf")

    with pytest.raises(ErrorArmado, match="3 de 4"):
        armar_varios([*buenos, roto])

    assert (tmp_path / "p1.pdf").is_file()
    assert (tmp_path / "p3.pdf").is_file()
    assert not (tmp_path / "roto.pdf").exists()


def test_guardar_encima_del_pdf_que_se_abrio(fuente):
    """Lo más natural del mundo: abrir un PDF, sacarle una página y
    guardar con el mismo nombre.

    El PDF de origen se lee a memoria justo por esto: en Windows no se
    puede renombrar sobre un archivo abierto, y el motor escribe a un
    temporal y renombra.
    """
    salida = armar_pdf(paginas_pdf(fuente, [0, 2]), fuente)
    assert salida == fuente
    assert textos_de(fuente) == ["UNO", "TRES"]


def test_guardar_encima_de_uno_de_varios_origenes(fuente, tmp_path):
    otro = pdf_con_texto(tmp_path / "otro.pdf", ["X"])
    salida = armar_pdf(paginas_pdf(fuente, [1]) + paginas_pdf(otro, [0]), otro)
    assert textos_de(salida) == ["DOS", "X"]
    assert textos_de(fuente) == ["UNO", "DOS", "TRES"], "el otro origen intacto"
