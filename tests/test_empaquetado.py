"""
tests/test_empaquetado.py
============================================================
Tests del .spec de PyInstaller.

Qué protegen
------------
El `.spec` lista a mano los módulos que PyInstaller no descubre solo. Esa
lista se pudre en silencio: renombrar un módulo la deja apuntando a algo
que ya no existe, y agregar uno nuevo no la actualiza. Nada de eso falla
en desarrollo —la app corre desde el código fuente— y el síntoma aparece
recién en el `.exe` ya distribuido, como un ImportError al abrir una
herramienta.

Pasó de verdad en la 0.13.0: `modules/documento_escaneado.py` pasó a
llamarse `modules/documento.py` y el spec siguió nombrando al viejo
durante todo el refactor.

Python puro, leyendo el .spec como texto: corre en el CI liviano y no
necesita tener PyInstaller instalado.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SPEC = RAIZ / "pdf_sign_assistant.spec"


def _texto_spec() -> str:
    return SPEC.read_text(encoding="utf-8")


def _modulos_listados() -> set[str]:
    return set(re.findall(r'"(modules\.[a-z_0-9]+)"', _texto_spec()))


def _modulos_reales() -> set[str]:
    return {f"modules.{p.stem}" for p in (RAIZ / "modules").glob("*.py")
            if p.stem != "__init__"}


def test_el_spec_existe():
    assert SPEC.is_file()


def test_el_spec_no_nombra_modulos_que_ya_no_existen():
    """Un renombre deja el spec apuntando al nombre viejo. PyInstaller sólo
    avisa por consola y el build sigue, así que nadie se entera."""
    fantasmas = _modulos_listados() - _modulos_reales()
    assert not fantasmas, (
        f"el .spec nombra módulos que ya no están: {sorted(fantasmas)}.\n"
        "Actualizá hiddenimports en pdf_sign_assistant.spec.")


def test_todos_los_modulos_estan_en_el_spec():
    """Al revés: un módulo nuevo que nadie agregó a la lista. PyInstaller
    suele encontrarlo solo siguiendo los imports, pero no cuando la carga
    es diferida o condicional — que es justo como se cargan las
    herramientas."""
    faltantes = _modulos_reales() - _modulos_listados()
    assert not faltantes, (
        f"módulos que no están en el .spec: {sorted(faltantes)}.\n"
        "Agregalos a hiddenimports en pdf_sign_assistant.spec.")


def test_cryptography_esta_entre_los_imports_ocultos():
    """pypdf la importa adentro de la función que descifra, así que el
    análisis estático de PyInstaller no la ve.

    Sin esto el .exe sale sin ella y cualquier PDF cifrado con AES —los
    que sólo restringen imprimir o copiar, que son la mayoría de los
    "protegidos"— deja de abrirse en la versión empaquetada aunque ande
    perfecto en desarrollo.
    """
    assert '"cryptography"' in _texto_spec(), (
        "falta cryptography en hiddenimports: los PDF cifrados con AES no "
        "se van a poder abrir desde el .exe")


def test_cryptography_esta_en_requirements():
    texto = (RAIZ / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^cryptography\b", texto, re.MULTILINE), (
        "cryptography tiene que estar declarada: sin ella pypdf ni siquiera "
        "intenta descifrar un PDF con AES")
