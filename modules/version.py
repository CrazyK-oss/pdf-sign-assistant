"""
modules/version.py
============================================================
Única fuente de verdad de la versión.

La leen:
  - la app (título de la ventana y log de arranque)
  - pdf_sign_assistant.spec (propiedades del .exe en Windows)
  - installer/pdf_sign_assistant.iss (versión del instalador)
  - .github/workflows/release.yml (nombre de los artefactos)

Al publicar: subir el número acá, agregarle su sección a CHANGELOG.md,
commitear y crear el tag `vX.Y.Z`.

El workflow verifica que el tag coincida con este valor, y que la versión
tenga su entrada en el CHANGELOG: de ahí salen las notas del Release y lo
que muestra el actualizador interno. Un test lo comprueba antes, así el
olvido no llega a gastar un build de Windows.
"""

from __future__ import annotations

__version__ = "0.13.0"

APP_NOMBRE = "PDF Sign Assistant"
APP_ID = "pdf-sign-assistant"
AUTOR = "CrazyK-oss"
URL_PROYECTO = "https://github.com/CrazyK-oss/pdf-sign-assistant"


def version_tupla() -> tuple[int, int, int, int]:
    """Versión como tupla de 4 enteros, que es lo que pide el recurso
    VERSIONINFO de Windows."""
    partes = [int(p) for p in __version__.split(".")[:3]]
    while len(partes) < 3:
        partes.append(0)
    return (*partes, 0)   # type: ignore[return-value]


if __name__ == "__main__":
    # Permite que el workflow y el instalador lean la versión:
    #   python -m modules.version
    print(__version__)
