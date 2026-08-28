"""
modules/changelog.py
============================================================
Lectura del CHANGELOG y de las notas de un Release.

Por qué existe
--------------
Las notas del Release eran una plantilla fija con instrucciones de
descarga: dónde bajar el .exe, la advertencia de SmartScreen, dónde
quedan los archivos. Útil para quien llega a la página de GitHub, pero
el actualizador interno mostraba **eso mismo** al avisar que había una
versión nueva. O sea: le decía al usuario cómo descargar algo que la app
ya estaba por descargar sola, y no le decía **qué cambió**.

Ahora la cadena es una sola:

    CHANGELOG.md
        │   el workflow de Release extrae la sección de la versión
        ▼
    cuerpo del Release  =  cambios  +  SENTINELA  +  cómo descargar
        │   la app pide el release a la API de GitHub
        ▼
    DialogoActualizacion  =  sólo la parte de antes de la sentinela

La sentinela es un comentario HTML: GitHub no lo muestra en la página del
Release, así que el lector no ve nada raro, y a la app le alcanza para
saber dónde cortar.

Python puro y sin Qt a propósito: lo usan el workflow (`python -m
modules.changelog 0.11.0`) y la app, y se puede probar en el CI liviano.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: Marca que separa los cambios de las instrucciones de descarga dentro
#: del cuerpo del Release. Es un comentario HTML para que GitHub no lo
#: renderice en la página.
SENTINELA = "<!--/cambios-->"

#: Nombre del archivo, relativo a la raíz del proyecto.
ARCHIVO = "CHANGELOG.md"

#: `## 0.11.0 — Título` o `## v0.11.0 — Título`. El título es opcional.
_ENCABEZADO = re.compile(r"^##\s+v?(\d+\.\d+(?:\.\d+)?)\s*(?:[—–-]\s*(.*))?$")


def ruta_changelog(base: Path | None = None) -> Path:
    """Ubicación del CHANGELOG.md, por defecto en la raíz del proyecto."""
    raiz = base or Path(__file__).resolve().parent.parent
    return raiz / ARCHIVO


def _texto(base: Path | None = None) -> str:
    try:
        return ruta_changelog(base).read_text(encoding="utf-8")
    except OSError:
        return ""


def versiones(texto: str | None = None, base: Path | None = None) -> list[str]:
    """Todas las versiones que tienen sección, de la más nueva a la más vieja."""
    contenido = texto if texto is not None else _texto(base)
    return [m.group(1) for linea in contenido.splitlines()
            if (m := _ENCABEZADO.match(linea))]


def seccion(version: str, texto: str | None = None,
            base: Path | None = None) -> str:
    """Devuelve la sección del CHANGELOG de `version`, sin su encabezado.

    Se compara por número, no por texto del encabezado: da igual que el
    título diga "Caja de herramientas" o que lleve una `v` adelante.
    Devuelve "" si esa versión no está.
    """
    contenido = texto if texto is not None else _texto(base)
    objetivo = str(version).lstrip("v").strip()

    lineas = contenido.splitlines()
    inicio = None
    for i, linea in enumerate(lineas):
        m = _ENCABEZADO.match(linea)
        if m is None:
            continue
        if inicio is None and m.group(1) == objetivo:
            inicio = i + 1
        elif inicio is not None:
            return "\n".join(lineas[inicio:i]).strip("\n")

    if inicio is None:
        return ""
    return "\n".join(lineas[inicio:]).strip("\n")


def titulo(version: str, texto: str | None = None,
           base: Path | None = None) -> str:
    """El título que acompaña al número de versión, si lo tiene."""
    contenido = texto if texto is not None else _texto(base)
    objetivo = str(version).lstrip("v").strip()
    for linea in contenido.splitlines():
        m = _ENCABEZADO.match(linea)
        if m is not None and m.group(1) == objetivo:
            return (m.group(2) or "").strip()
    return ""


def notas_de_cambios(cuerpo: str) -> str:
    """Extrae del cuerpo de un Release sólo la parte de cambios.

    Corta en la sentinela. Si no está —releases viejos, o publicados a
    mano— devuelve el cuerpo entero: es preferible mostrar de más que
    dejar el diálogo en blanco.
    """
    texto = (cuerpo or "").strip()
    if not texto:
        return ""
    cabeza = texto.split(SENTINELA, 1)[0].strip()
    return cabeza or texto


def cuerpo_release(cambios: str, instrucciones: str) -> str:
    """Arma el cuerpo del Release: cambios, sentinela e instrucciones."""
    partes = [cambios.strip() or "_Sin notas para esta versión._",
              SENTINELA,
              instrucciones.strip()]
    return "\n\n".join(p for p in partes if p)


if __name__ == "__main__":
    # Lo llama el workflow de Release:
    #     python -m modules.changelog 0.11.0            → los cambios
    #     python -m modules.changelog --titulo 0.11.0   → sólo el título
    #
    # Con los cambios sale con código 1 si esa versión no tiene sección,
    # para que el build se detenga antes de publicar notas vacías. El
    # título, en cambio, es decorativo: si falta, imprime nada y sigue.
    argumentos = [a for a in sys.argv[1:] if a != "--titulo"]
    solo_titulo = "--titulo" in sys.argv[1:]
    pedida = argumentos[0] if argumentos else ""

    if not pedida:
        print("Uso: python -m modules.changelog [--titulo] <version>",
              file=sys.stderr)
        raise SystemExit(2)

    if solo_titulo:
        print(titulo(pedida))
        raise SystemExit(0)

    contenido = seccion(pedida)
    if not contenido:
        print(f"No hay sección para la versión {pedida} en {ARCHIVO}. "
              f"Versiones presentes: {', '.join(versiones()) or 'ninguna'}",
              file=sys.stderr)
        raise SystemExit(1)
    print(contenido)
