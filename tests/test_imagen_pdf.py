"""
tests/test_imagen_pdf.py
============================================================
Tests de la conversión imagen → PDF y del tamaño de salida.

Por qué importan
----------------
El documento firmado existe para mandarse por correo. Hasta la 0.11.1 la
imagen se embebía sin pérdida y cada hoja escaneada a 600 dpi pesaba
3,4 MB: con seis hojas el archivo ya no entraba en Outlook, y eso se
descubría al final de todo el trabajo, cuando el correo lo rechazaba.

La parte de presets y de límites es Python puro y corre en el CI liviano.
Los que arman PDFs de verdad necesitan Pillow/reportlab y llevan la marca
`integracion`.
"""

from __future__ import annotations

import pytest

from modules.imagen_pdf import (
    ALTA,
    CALIDAD_DEFECTO,
    CALIDADES,
    EQUILIBRADA,
    LIMITE_CORREO_MB,
    MINIMA,
    ORDEN,
    SIN_PERDIDA,
    calidad,
    excede_limite,
    formatear_peso,
    opciones_calidad,
    siguiente_mas_liviana,
)

MB = 1024 * 1024


# ── Presets ───────────────────────────────────────────────────────────────────

def test_el_defecto_comprime():
    """Si el default fuera sin pérdida no habríamos arreglado nada."""
    assert not CALIDAD_DEFECTO.sin_perdida
    assert CALIDAD_DEFECTO is EQUILIBRADA


def test_solo_sin_perdida_es_sin_perdida():
    assert SIN_PERDIDA.sin_perdida
    for cal in (ALTA, EQUILIBRADA, MINIMA):
        assert not cal.sin_perdida, cal.clave


def test_los_presets_bajan_en_calidad_segun_el_orden():
    """ORDEN va de peor a mejor compresión; los dpi tienen que acompañar."""
    con_perdida = [CALIDADES[k] for k in ORDEN if not CALIDADES[k].sin_perdida]
    dpis = [c.dpi_max for c in con_perdida]
    assert dpis == sorted(dpis, reverse=True), dpis
    jotas = [c.jpeg for c in con_perdida]
    assert jotas == sorted(jotas, reverse=True), jotas


def test_la_calidad_jpeg_esta_en_rango():
    for cal in CALIDADES.values():
        assert 0 <= cal.jpeg <= 95, cal.clave


def test_todas_tienen_descripcion_util():
    for cal in CALIDADES.values():
        assert len(cal.descripcion) > 30, cal.clave
        assert cal.nombre, cal.clave


@pytest.mark.parametrize("entrada", ["equilibrada", "alta", "minima",
                                     "sin_perdida"])
def test_calidad_resuelve_las_claves(entrada):
    assert calidad(entrada).clave == entrada


@pytest.mark.parametrize("entrada", ["", None, "no-existe", "ALTA"])
def test_calidad_cae_al_defecto_ante_algo_raro(entrada):
    """Un config.json editado a mano no debe romper el guardado."""
    assert calidad(entrada) is CALIDAD_DEFECTO


def test_calidad_acepta_un_preset_ya_resuelto():
    assert calidad(ALTA) is ALTA


def test_opciones_van_de_la_mas_liviana_a_la_mas_pesada():
    claves = [c for c, _, _ in opciones_calidad()]
    assert claves[0] == "minima"
    assert claves[-1] == "sin_perdida"
    assert set(claves) == set(CALIDADES)


# ── Bajar de calidad ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("desde, esperada", [
    ("sin_perdida", "alta"),
    ("alta", "equilibrada"),
    ("equilibrada", "minima"),
])
def test_siguiente_mas_liviana(desde, esperada):
    assert siguiente_mas_liviana(desde).clave == esperada


def test_desde_la_mas_liviana_no_hay_siguiente():
    """La UI usa el None para decir 'no hay nada más que hacer'."""
    assert siguiente_mas_liviana("minima") is None


# ── Límite de adjunto ─────────────────────────────────────────────────────────

def test_el_limite_por_defecto_es_el_de_outlook():
    assert LIMITE_CORREO_MB == 20


@pytest.mark.parametrize("peso, excede", [
    (1 * MB, False),
    (19 * MB, False),
    (20 * MB, False),          # justo en el límite, entra
    (21 * MB, True),
])
def test_excede_limite(peso, excede):
    assert excede_limite(peso) is excede


def test_el_limite_es_configurable():
    """Muchas organizaciones lo bajan a 10 MB."""
    assert excede_limite(15 * MB, limite_mb=10)
    assert not excede_limite(15 * MB, limite_mb=25)


def test_un_limite_absurdo_no_rompe():
    assert excede_limite(5 * MB, limite_mb=0)


@pytest.mark.parametrize("bytes_, texto", [
    (512, "512 B"),
    (2048, "2 kB"),
    (int(2.4 * MB), "2,4 MB"),
    (int(20 * MB), "20,0 MB"),
])
def test_formatear_peso(bytes_, texto):
    assert formatear_peso(bytes_) == texto


def test_formatear_peso_usa_coma_decimal():
    assert "." not in formatear_peso(int(3.5 * MB))


# ── Conversión de verdad ──────────────────────────────────────────────────────

@pytest.mark.integracion
class TestConversion:
    """Necesitan Pillow y reportlab; arman PDFs y los miden."""

    @staticmethod
    def _hoja(tmp_path, dpi=600, nombre="hoja.png"):
        Image = pytest.importorskip("PIL.Image")
        ImageDraw = pytest.importorskip("PIL.ImageDraw")
        import random

        random.seed(11)
        w, h = int(8.27 * dpi), int(11.69 * dpi)
        img = Image.new("RGB", (w, h), (252, 251, 247))
        d = ImageDraw.Draw(img)
        px = img.load()
        # El ruido del papel es lo que hace que un escaneo real no
        # comprima como una imagen plana.
        for _ in range(w * h // 60):
            x, y = random.randrange(w), random.randrange(h)
            v = random.randint(228, 250)
            px[x, y] = (v, v, v - random.randint(0, 6))
        m = int(dpi * 0.9)
        d.rectangle([m, m, w - m, m + dpi // 5], fill=(30, 38, 50))
        ruta = tmp_path / nombre
        img.save(ruta, dpi=(dpi, dpi))
        return ruta

    def test_comprimir_achica_muchisimo(self, tmp_path):
        """El caso que motivó todo: una hoja firmada a 600 dpi."""
        pytest.importorskip("reportlab")
        from modules.imagen_pdf import borrar_si_existe, convertir_imagen_a_pdf

        hoja = self._hoja(tmp_path)
        pesos = {}
        for clave in ORDEN:
            pdf = convertir_imagen_a_pdf(str(hoja), 0, CALIDADES[clave])
            try:
                pesos[clave] = pdf.stat().st_size if hasattr(pdf, "stat") \
                    else __import__("pathlib").Path(pdf).stat().st_size
            finally:
                borrar_si_existe(pdf)

        assert pesos["equilibrada"] < pesos["sin_perdida"] / 5, (
            f"la compresión no rinde lo esperado: {pesos}")
        assert pesos["minima"] < pesos["equilibrada"] < pesos["alta"]

    def test_una_hoja_firmada_entra_holgada_en_un_correo(self, tmp_path):
        """Con el default, tres hojas a 600 dpi tienen que entrar de sobra."""
        pytest.importorskip("reportlab")
        from pathlib import Path

        from modules.imagen_pdf import borrar_si_existe, convertir_imagen_a_pdf

        hoja = self._hoja(tmp_path)
        pdf = convertir_imagen_a_pdf(str(hoja), 0, CALIDAD_DEFECTO)
        try:
            por_pagina = Path(pdf).stat().st_size
        finally:
            borrar_si_existe(pdf)

        assert not excede_limite(por_pagina * 3), (
            f"tres hojas darían {formatear_peso(por_pagina * 3)}")
        # Y el margen tiene que ser amplio, no de milímetros
        assert por_pagina * 20 < LIMITE_CORREO_MB * MB, (
            f"a {formatear_peso(por_pagina)} por página sólo entran "
            f"{int(LIMITE_CORREO_MB * MB / por_pagina)} páginas")

    def test_se_embebe_como_jpeg_y_no_se_recodifica(self, tmp_path):
        """reportlab tiene que pasar el JPEG tal cual (DCTDecode). Si lo
        recodificara habría doble pérdida y el ahorro sería menor."""
        pytest.importorskip("reportlab")
        pymupdf = pytest.importorskip("pymupdf")
        from modules.imagen_pdf import borrar_si_existe, convertir_imagen_a_pdf

        hoja = self._hoja(tmp_path)
        pdf = convertir_imagen_a_pdf(str(hoja), 0, EQUILIBRADA)
        try:
            doc = pymupdf.open(pdf)
            xref = doc[0].get_images(full=True)[0][0]
            assert doc.extract_image(xref)["ext"] == "jpeg"
            doc.close()
        finally:
            borrar_si_existe(pdf)

    def test_sin_perdida_conserva_el_formato_original(self, tmp_path):
        pytest.importorskip("reportlab")
        pymupdf = pytest.importorskip("pymupdf")
        from modules.imagen_pdf import borrar_si_existe, convertir_imagen_a_pdf

        hoja = self._hoja(tmp_path, dpi=150)
        pdf = convertir_imagen_a_pdf(str(hoja), 0, SIN_PERDIDA)
        try:
            doc = pymupdf.open(pdf)
            xref = doc[0].get_images(full=True)[0][0]
            assert doc.extract_image(xref)["ext"] != "jpeg"
            doc.close()
        finally:
            borrar_si_existe(pdf)

    def test_la_pagina_conserva_su_tamano_fisico(self, tmp_path):
        """Remuestrear cambia los píxeles, no los centímetros: si la página
        del PDF cambiara de tamaño, la firma no caería donde corresponde."""
        pytest.importorskip("reportlab")
        pymupdf = pytest.importorskip("pymupdf")
        from modules.imagen_pdf import borrar_si_existe, convertir_imagen_a_pdf

        hoja = self._hoja(tmp_path)
        medidas = {}
        for clave in ("sin_perdida", "equilibrada", "minima"):
            pdf = convertir_imagen_a_pdf(str(hoja), 0, CALIDADES[clave])
            try:
                doc = pymupdf.open(pdf)
                medidas[clave] = (round(doc[0].rect.width),
                                  round(doc[0].rect.height))
                doc.close()
            finally:
                borrar_si_existe(pdf)

        # Hasta 1 punto (0,35 mm) de diferencia es inevitable: JFIF guarda
        # la densidad como entero, así que remuestrear no puede conservar
        # px/dpi exacto. Más que eso sería un error de cálculo.
        anchos = [a for a, _ in medidas.values()]
        altos = [h for _, h in medidas.values()]
        assert max(anchos) - min(anchos) <= 1, (
            f"la página cambia de ancho según la calidad: {medidas}")
        assert max(altos) - min(altos) <= 1, (
            f"la página cambia de alto según la calidad: {medidas}")
        assert 590 <= anchos[0] <= 600 and 835 <= altos[0] <= 848, medidas

    def test_una_imagen_sin_dpi_declarado_no_rompe(self, tmp_path):
        """Muchos escáneres no lo declaran; antes se dividía por ese valor."""
        Image = pytest.importorskip("PIL.Image")
        pytest.importorskip("reportlab")
        from pathlib import Path

        from modules.imagen_pdf import borrar_si_existe, convertir_imagen_a_pdf

        ruta = tmp_path / "sin_dpi.png"
        Image.new("RGB", (800, 1100), (240, 240, 240)).save(ruta)
        pdf = convertir_imagen_a_pdf(str(ruta), 0, EQUILIBRADA)
        try:
            assert Path(pdf).stat().st_size > 0
        finally:
            borrar_si_existe(pdf)

    def test_una_imagen_con_transparencia_no_rompe(self, tmp_path):
        """JPEG no admite alpha: hay que componer sobre blanco antes."""
        Image = pytest.importorskip("PIL.Image")
        pytest.importorskip("reportlab")
        from pathlib import Path

        from modules.imagen_pdf import borrar_si_existe, convertir_imagen_a_pdf

        ruta = tmp_path / "alpha.png"
        Image.new("RGBA", (600, 800), (10, 200, 10, 90)).save(ruta)
        pdf = convertir_imagen_a_pdf(str(ruta), 0, EQUILIBRADA)
        try:
            assert Path(pdf).stat().st_size > 0
        finally:
            borrar_si_existe(pdf)

    def test_una_imagen_ilegible_cae_al_original_sin_explotar(self, tmp_path):
        """Comprimir es una mejora, no un requisito."""
        from modules.imagen_pdf import preparar_para_pdf

        roto = tmp_path / "roto.png"
        roto.write_bytes(b"no soy un PNG")
        ruta, temporal = preparar_para_pdf(str(roto), EQUILIBRADA)
        assert ruta == str(roto) and temporal is False

    def test_no_se_remuestrea_hacia_arriba(self, tmp_path):
        """Una imagen de 100 dpi no debe inflarse a 200 por el preset."""
        Image = pytest.importorskip("PIL.Image")
        from modules.imagen_pdf import borrar_si_existe, preparar_para_pdf

        ruta = tmp_path / "baja.png"
        Image.new("RGB", (400, 550), (200, 200, 200)).save(ruta, dpi=(100, 100))
        salida, temporal = preparar_para_pdf(str(ruta), EQUILIBRADA)
        try:
            with Image.open(salida) as img:
                assert img.size == (400, 550)
        finally:
            if temporal:
                borrar_si_existe(salida)
