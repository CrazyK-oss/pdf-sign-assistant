"""
tests/test_changelog.py
============================================================
Tests del CHANGELOG y de las notas que ve el actualizador.

El más importante del archivo es
`test_la_version_actual_tiene_su_seccion_en_el_changelog`: sin él, subir
el número en `modules/version.py` y olvidarse del CHANGELOG hace que el
build de Release falle recién en el runner de Windows, después de haber
compilado el .exe, o —peor, si el chequeo no existiera— publica un aviso
de actualización que no dice qué cambió. Que es exactamente el problema
que este módulo vino a resolver.

Todo es Python puro: corre en el CI liviano.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from modules.changelog import (
    SENTINELA,
    cuerpo_release,
    instrucciones_descarga,
    notas_de_cambios,
    notas_release,
    ruta_changelog,
    seccion,
    titulo,
    versiones,
)
from modules.version import __version__

RAIZ = Path(__file__).resolve().parent.parent

EJEMPLO = """# Changelog

Preámbulo que no pertenece a ninguna versión.

## 0.3.0 — Tercera

- cambio nuevo
- otro cambio

## 0.2.0 — Segunda

- algo viejo

## 0.1.0

- el principio
"""


# ── Extracción de secciones ───────────────────────────────────────────────────

def test_extrae_la_seccion_pedida():
    assert seccion("0.2.0", EJEMPLO) == "- algo viejo"


def test_la_primera_seccion_no_se_come_el_preambulo():
    """El texto anterior al primer encabezado es introducción del archivo,
    no cambios de la versión más nueva."""
    resultado = seccion("0.3.0", EJEMPLO)
    assert "Preámbulo" not in resultado
    assert resultado == "- cambio nuevo\n- otro cambio"


def test_la_ultima_seccion_llega_hasta_el_final():
    assert seccion("0.1.0", EJEMPLO) == "- el principio"


def test_una_version_que_no_esta_devuelve_vacio():
    assert seccion("9.9.9", EJEMPLO) == ""


def test_la_v_del_tag_es_opcional():
    assert seccion("v0.2.0", EJEMPLO) == seccion("0.2.0", EJEMPLO)


def test_tambien_lee_encabezados_escritos_con_v():
    texto = "## v1.2.3 — Con uve\n\n- cambio\n"
    assert seccion("1.2.3", texto) == "- cambio"
    assert titulo("1.2.3", texto) == "Con uve"


def test_versiones_en_orden_de_aparicion():
    assert versiones(EJEMPLO) == ["0.3.0", "0.2.0", "0.1.0"]


def test_titulo_opcional():
    assert titulo("0.3.0", EJEMPLO) == "Tercera"
    assert titulo("0.1.0", EJEMPLO) == ""       # ese encabezado no tiene título
    assert titulo("9.9.9", EJEMPLO) == ""


def test_un_changelog_vacio_no_rompe():
    assert seccion("1.0.0", "") == ""
    assert versiones("") == []


# ── Notas que ve el actualizador ──────────────────────────────────────────────

def test_las_notas_cortan_en_la_sentinela():
    """Es el punto de todo el cambio: el usuario tiene que ver los cambios,
    no las instrucciones para descargar algo que la app ya está bajando."""
    cuerpo = cuerpo_release("- arreglado el escáner", "## Descargar\n\nBajá el exe.")
    assert notas_de_cambios(cuerpo) == "- arreglado el escáner"
    assert "Descargar" not in notas_de_cambios(cuerpo)


def test_sin_sentinela_se_muestra_todo():
    """Los releases viejos (o los publicados a mano) no la tienen. Mejor
    mostrar de más que dejar el diálogo en blanco."""
    viejo = "## Descargar\n\nInstrucciones de siempre."
    assert notas_de_cambios(viejo) == viejo


def test_notas_vacias():
    assert notas_de_cambios("") == ""
    assert notas_de_cambios("   \n  ") == ""
    assert notas_de_cambios(None) == ""          # type: ignore[arg-type]


def test_un_cuerpo_que_empieza_con_la_sentinela_no_queda_en_blanco():
    """Si por error los cambios salieran vacíos, es mejor caer al cuerpo
    entero que mostrar un panel vacío."""
    cuerpo = f"{SENTINELA}\n\n## Descargar\n\nBajá el exe."
    assert "Descargar" in notas_de_cambios(cuerpo)


def test_cuerpo_release_arma_las_tres_partes():
    cuerpo = cuerpo_release("- un cambio", "## Descargar")
    assert cuerpo.index("- un cambio") < cuerpo.index(SENTINELA) \
        < cuerpo.index("## Descargar"), "los cambios van primero"


def test_cuerpo_release_sin_cambios_deja_un_texto_de_relleno():
    cuerpo = cuerpo_release("", "## Descargar")
    assert notas_de_cambios(cuerpo) == "_Sin notas para esta versión._"


def test_la_sentinela_es_un_comentario_html():
    """Así GitHub no la muestra en la página del Release."""
    assert SENTINELA.startswith("<!--") and SENTINELA.endswith("-->")


# ── El CHANGELOG de verdad ────────────────────────────────────────────────────

def test_el_changelog_existe():
    assert ruta_changelog().is_file()


def test_la_version_actual_tiene_su_seccion_en_el_changelog():
    """El guardián: subir la versión y olvidar el CHANGELOG falla acá, no
    en el runner de Windows después de compilar el .exe."""
    contenido = seccion(__version__)
    assert contenido, (
        f"CHANGELOG.md no tiene sección para la versión {__version__}.\n"
        f"Agregá un encabezado '## {__version__} — Título' con los cambios.\n"
        f"Versiones presentes: {', '.join(versiones())}")
    assert len(contenido.splitlines()) >= 3, (
        f"La sección de {__version__} es demasiado escueta para servir de "
        "notas de release")


def test_las_versiones_del_changelog_estan_bien_formadas():
    for v in versiones():
        partes = v.split(".")
        assert len(partes) == 3, f"{v} debería ser X.Y.Z para coincidir con el tag"
        assert all(p.isdigit() for p in partes), v


def test_no_hay_versiones_repetidas():
    lista = versiones()
    assert len(lista) == len(set(lista)), f"versiones duplicadas en {lista}"


def test_la_version_actual_es_la_primera():
    """La entrada más nueva va arriba; si no, el lector ve primero lo viejo."""
    assert versiones()[0] == __version__


# ── El comando que usa el workflow ────────────────────────────────────────────

def _ejecutar(*argumentos):
    return subprocess.run(
        [sys.executable, "-m", "modules.changelog", *argumentos],
        capture_output=True, text=True, cwd=RAIZ)


def test_el_comando_imprime_la_seccion():
    r = _ejecutar(__version__)
    assert r.returncode == 0
    assert r.stdout.strip() == seccion(__version__)


def test_el_comando_falla_si_la_version_no_esta():
    """El workflow depende de este código de salida para frenar el build
    antes de publicar notas vacías."""
    r = _ejecutar("9.9.9")
    assert r.returncode == 1
    assert "9.9.9" in r.stderr


def test_el_comando_devuelve_el_titulo():
    r = _ejecutar("--titulo", __version__)
    assert r.returncode == 0
    assert r.stdout.strip() == titulo(__version__)


def test_el_comando_sin_argumentos_explica_el_uso():
    r = _ejecutar()
    assert r.returncode == 2
    assert "Uso:" in r.stderr


@pytest.mark.parametrize("version", ["0.10.1", "0.10.0"])
def test_las_versiones_ya_publicadas_siguen_teniendo_seccion(version):
    """Si alguien reordena el CHANGELOG y se lleva puesta una entrada
    vieja, se pierde el historial que enlaza cada release."""
    assert seccion(version)

# ── Codificación de la salida ─────────────────────────────────────────────────

def _ejecutar_en_consola_no_utf8(*argumentos):
    """Como en el runner de Windows, donde la consola es cp1252."""
    entorno = dict(os.environ, PYTHONIOENCODING="cp1252")
    return subprocess.run(
        [sys.executable, "-m", "modules.changelog", *argumentos],
        capture_output=True, cwd=RAIZ, env=entorno)      # bytes, sin decodificar


def _texto_utf8(salida: bytes) -> str:
    """Decodifica la salida capturada como UTF-8 y normaliza los saltos.

    Los tests de esta sección capturan **bytes** a propósito: decodificar
    con `text=True` dejaría que Python arregle solo lo que queremos
    comprobar. El precio es que hay que traducir los saltos a mano: en
    Windows el modo texto convierte cada `\\n` en `\\r\\n` al escribir, así
    que los bytes traen `\\r` que el CHANGELOG no tiene. Es cosmético para
    el Release —GitHub los ignora— pero rompía la comparación exacta.
    """
    return salida.decode("utf-8").replace("\r\n", "\n")


def test_texto_utf8_normaliza_los_saltos_de_windows():
    """En Linux no hay traducción de saltos, así que el caso de Windows
    sólo se puede probar acá. Sin esta normalización los tests de abajo
    pasan en Linux y fallan en el runner de Windows, que es justo donde
    corre el Release."""
    assert _texto_utf8(b"uno\r\ndos\r\n") == "uno\ndos\n"
    assert _texto_utf8("embebía\r\n".encode()) == "embebía\n"


def test_la_salida_es_utf8_aunque_la_consola_no_lo_sea():
    """El bug que salió publicado en la 0.12.0.

    En Windows, `python -m modules.changelog > cambios.md` escribía con la
    codificación local (cp1252): 'embebía' quedaba como b'embeb\xeda'.
    GitHub lee las notas del Release como UTF-8, así que cada tilde
    aparecía como un rombo con un signo de pregunta.
    """
    r = _ejecutar_en_consola_no_utf8(__version__)
    assert r.returncode == 0

    texto = _texto_utf8(r.stdout)         # revienta si no es UTF-8 válido
    assert texto.strip() == seccion(__version__)

    # Y que no haya pasado de casualidad: en cp1252 una 'í' ocupa un solo
    # byte (0xED) y en UTF-8 ocupa dos (0xC3 0xAD). Buscar la secuencia
    # UTF-8 en los bytes crudos deja el bug a la vista aunque alguien
    # afloje la comparación de arriba.
    acentuadas = [c for c in seccion(__version__) if ord(c) > 127]
    assert acentuadas, "hace falta al menos un acento para probar algo"
    for c in acentuadas:
        assert c.encode("utf-8") in r.stdout, f"{c!r} no salió en UTF-8"


def test_el_titulo_tambien_sale_en_utf8():
    r = _ejecutar_en_consola_no_utf8("--titulo", __version__)
    assert r.returncode == 0
    assert _texto_utf8(r.stdout).strip() == titulo(__version__)


def test_el_changelog_tiene_acentos_que_verificar():
    """Salvaguarda de los dos tests de arriba: si el CHANGELOG fuera todo
    ASCII pasarían en verde sin comprobar nada."""
    acentuados = set("áéíóúñÁÉÍÓÚÑ¿¡—")
    texto = ruta_changelog().read_text(encoding="utf-8")
    assert acentuados & set(texto), "el CHANGELOG no tiene caracteres no-ASCII"
    assert acentuados & set(seccion(__version__)), (
        f"la sección de {__version__} no tiene acentos que probar")


# ── El cuerpo completo del Release ────────────────────────────────────────────

def test_las_notas_llevan_los_cambios_primero():
    cuerpo = notas_release(__version__, f"v{__version__}")
    assert cuerpo.index(SENTINELA) < cuerpo.index("## Descargar")
    assert notas_de_cambios(cuerpo) == seccion(__version__)


def test_el_enlace_al_changelog_apunta_al_tag_y_no_a_main():
    """Una versión se puede publicar desde una rama sin mergear: el enlace
    a main daría 404 hasta que alguien la integre."""
    cuerpo = notas_release("0.12.0", "v0.12.0")
    assert "blob/v0.12.0/CHANGELOG.md" in cuerpo
    assert "blob/main/CHANGELOG.md" not in cuerpo


def test_sin_tag_el_enlace_se_deduce_de_la_version():
    assert "blob/v1.2.3/" in instrucciones_descarga("1.2.3")


def test_las_instrucciones_nombran_los_archivos_de_esa_version():
    texto = instrucciones_descarga("9.9.9")
    assert "PDFSignAssistant-9.9.9-Setup.exe" in texto
    assert "PDFSignAssistant-9.9.9-portable.zip" in texto


def test_las_notas_fallan_si_no_hay_seccion():
    """Publicar notas vacías es peor que no publicar."""
    with pytest.raises(ValueError, match="9.9.9"):
        notas_release("9.9.9")


def test_el_comando_notas_imprime_el_cuerpo_entero():
    r = _ejecutar("--notas", __version__, f"v{__version__}")
    assert r.returncode == 0
    assert SENTINELA in r.stdout
    assert "## Descargar" in r.stdout


def test_el_comando_notas_falla_si_no_hay_seccion():
    r = _ejecutar("--notas", "9.9.9")
    assert r.returncode == 1
    assert "9.9.9" in r.stderr


def test_el_comando_notas_sale_en_utf8():
    """El mismo bug de la 0.12.0, ahora sobre el cuerpo completo."""
    r = _ejecutar_en_consola_no_utf8("--notas", __version__, f"v{__version__}")
    assert r.returncode == 0
    texto = _texto_utf8(r.stdout)           # revienta si no es UTF-8
    assert "Configuración" in texto and "Más información" in texto
