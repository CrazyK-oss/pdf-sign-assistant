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

#: Repositorio al que apuntan los enlaces de las notas.
REPO = "CrazyK-oss/pdf-sign-assistant"

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


def instrucciones_descarga(version: str, tag: str = "",
                           repo: str = REPO) -> str:
    """La mitad de abajo del Release: qué archivo bajar y qué esperar.

    Vive acá y no dentro del YAML del workflow por dos razones: es
    contenido y no lógica de CI, y así lo pueden generar tanto el job que
    publica como el que corrige las notas de un release ya salido, sin
    tener el mismo texto escrito en dos lados.

    El enlace al CHANGELOG apunta al TAG, no a main: una versión se puede
    publicar desde una rama que todavía no se mergeó, y ahí el enlace a
    main daría 404.
    """
    ref = tag or f"v{version}"
    return f"""## Descargar

| Archivo | Para quién |
|---------|-----------|
| `PDFSignAssistant-{version}-Setup.exe` | **La mayoría.** Instalador normal: no pide permisos de administrador y crea el acceso directo. |
| `PDFSignAssistant-{version}-portable.zip` | Sin instalar nada (por ejemplo, desde un pendrive). Descomprimir y ejecutar. |

> Si ya tenés la aplicación instalada no hace falta que bajes nada:
> te va a avisar sola y se actualiza desde adentro.

### La primera vez, Windows va a advertirte

La aplicación **no está firmada digitalmente**, así que SmartScreen muestra
*"Windows protegió su PC"*. Para continuar: **Más información → Ejecutar de todas formas**.

Podés verificar la integridad de la descarga con `SHA256SUMS.txt`.

### Dónde quedan tus archivos

- Documentos firmados: `Documentos\\PDF Sign Assistant`
- Configuración y logs: `%LOCALAPPDATA%\\PDF Sign Assistant`

Al desinstalar, **tus documentos no se borran**.

---

El historial completo está en el [CHANGELOG](https://github.com/{repo}/blob/{ref}/CHANGELOG.md)."""


def notas_release(version: str, tag: str = "", repo: str = REPO,
                  texto: str | None = None, base=None) -> str:
    """El cuerpo completo del Release para `version`.

    Lanza ValueError si esa versión no tiene sección: publicar unas notas
    vacías es peor que no publicar.
    """
    cambios = seccion(version, texto, base)
    if not cambios:
        raise ValueError(
            f"No hay sección para la versión {version} en {ARCHIVO}. "
            f"Versiones presentes: {', '.join(versiones(texto, base)) or 'ninguna'}")
    return cuerpo_release(cambios, instrucciones_descarga(version, tag, repo))


def _forzar_utf8_en_salida() -> None:
    """Escribe la salida en UTF-8 pase lo que pase con la consola.

    Sin esto, en Windows `python -m modules.changelog > cambios.md` usa la
    codificación local (cp1252) y las tildes salen como bytes sueltos:
    'embebía' se guarda como b'embeb\\xeda'. GitHub lee las notas del
    Release como UTF-8, así que cada acento aparecía como un rombo con un
    signo de pregunta. Pasó de verdad al publicar la 0.12.0.

    El CHANGELOG se lee siempre en UTF-8; el problema estaba sólo al
    escribir.
    """
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")     # type: ignore[union-attr]
        except (AttributeError, ValueError):        # pragma: no cover
            pass                                    # consola rara: seguimos


if __name__ == "__main__":
    # Lo llama el workflow de Release:
    #     python -m modules.changelog 0.11.0            → los cambios
    #     python -m modules.changelog --titulo 0.11.0   → sólo el título
    #     python -m modules.changelog --notas 0.12.0 v0.12.0
    #                                                 → el cuerpo entero
    #
    # Con los cambios sale con código 1 si esa versión no tiene sección,
    # para que el build se detenga antes de publicar notas vacías. El
    # título, en cambio, es decorativo: si falta, imprime nada y sigue.
    _forzar_utf8_en_salida()

    banderas = {"--titulo", "--notas"}
    argumentos = [a for a in sys.argv[1:] if a not in banderas]
    solo_titulo = "--titulo" in sys.argv[1:]
    cuerpo_completo = "--notas" in sys.argv[1:]

    # --notas admite el tag como segundo argumento, para los enlaces.
    pedida = argumentos[0] if argumentos else ""
    tag_pedido = argumentos[1] if len(argumentos) > 1 else ""

    if not pedida:
        print("Uso: python -m modules.changelog [--titulo|--notas] "
              "<version> [tag]", file=sys.stderr)
        raise SystemExit(2)

    if solo_titulo:
        print(titulo(pedida))
        raise SystemExit(0)

    if cuerpo_completo:
        try:
            print(notas_release(pedida, tag_pedido))
        except ValueError as e:
            print(str(e), file=sys.stderr)
            raise SystemExit(1) from None
        raise SystemExit(0)

    contenido = seccion(pedida)
    if not contenido:
        print(f"No hay sección para la versión {pedida} en {ARCHIVO}. "
              f"Versiones presentes: {', '.join(versiones()) or 'ninguna'}",
              file=sys.stderr)
        raise SystemExit(1)
    print(contenido)
