"""
modules/errores.py
============================================================
Manejador global de excepciones.

Por qué hace falta
------------------
El .exe se compila con `console=False`. Si una excepción escapa de un
slot de Qt o del arranque, Python la imprime en una consola que no
existe: la aplicación se cierra —o peor, queda a medias— y el usuario no
tiene nada que contar más allá de "se cerró solo".

Con esto, cualquier excepción no atrapada:
  1. queda registrada en el log, con traceback completo;
  2. se le muestra al usuario en un diálogo que dice qué pasó y dónde
     está el archivo de log para reportarlo.

La lógica de formateo es pura (sin Qt) para poder testearla.
"""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

log = logging.getLogger(__name__)

# Evita la cascada: si el propio manejador falla, o si una excepción se
# repite en bucle (típico en un paint event roto), no llenamos la pantalla
# de diálogos.
MAX_DIALOGOS = 3
_mostrados = 0


def formatear_reporte(tipo, valor, tb, *, version: str = "",
                      ruta_log: Path | str | None = None) -> tuple[str, str]:
    """Arma (mensaje_para_el_usuario, detalle_para_el_log).

    El mensaje es corto y accionable; el detalle lleva el traceback
    completo, que es lo que sirve para diagnosticar.
    """
    nombre = getattr(tipo, "__name__", str(tipo))
    resumen_error = str(valor).strip() or nombre

    partes = [
        "La aplicación encontró un error inesperado.",
        "",
        f"Detalle: {resumen_error}",
    ]
    if ruta_log:
        partes += [
            "",
            "Se guardó un registro completo en:",
            str(ruta_log),
            "",
            "Ese archivo es lo más útil para adjuntar al reportar el problema.",
        ]
    mensaje = "\n".join(partes)

    detalle = "".join(traceback.format_exception(tipo, valor, tb))
    if version:
        detalle = f"Versión {version}\n{detalle}"
    return mensaje, detalle


def instalar(*, version: str = "", ruta_log: Path | str | None = None,
             mostrar_dialogo=None) -> None:
    """Instala el manejador global de excepciones.

    `mostrar_dialogo` es un callable(mensaje) — se inyecta desde main.py
    para no meter Qt en este módulo. Si es None, sólo se registra en el log.
    """
    anterior = sys.excepthook

    def manejador(tipo, valor, tb):
        global _mostrados

        # Ctrl+C sigue comportándose como siempre
        if issubclass(tipo, KeyboardInterrupt):
            anterior(tipo, valor, tb)
            return

        mensaje, detalle = formatear_reporte(
            tipo, valor, tb, version=version, ruta_log=ruta_log)
        log.critical("Excepción no atrapada:\n%s", detalle)

        if mostrar_dialogo is not None and _mostrados < MAX_DIALOGOS:
            _mostrados += 1
            try:
                mostrar_dialogo(mensaje)
            except Exception:                        # noqa: BLE001
                # Un fallo mostrando el error no puede tapar el error real
                log.exception("No se pudo mostrar el diálogo de error")

        anterior(tipo, valor, tb)

    sys.excepthook = manejador

    # Los hilos tienen su propio hook desde Python 3.8: sin esto, una
    # excepción en un QThread se pierde igual que antes.
    def manejador_hilo(args):
        if issubclass(args.exc_type, SystemExit):
            return
        _, detalle = formatear_reporte(
            args.exc_type, args.exc_value, args.exc_traceback, version=version)
        log.critical("Excepción no atrapada en el hilo %s:\n%s",
                     getattr(args.thread, "name", "?"), detalle)

    import threading
    threading.excepthook = manejador_hilo
