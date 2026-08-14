"""
tests/test_errores.py
============================================================
Tests del manejador global de excepciones (modules/errores.py).

Importa porque es la última red: si una excepción escapa en el .exe
—compilado con console=False— sin esto la app muere en silencio y el
usuario no tiene nada que reportar.
"""

import logging

from modules.errores import formatear_reporte, instalar


def _excepcion(mensaje="algo salió mal"):
    try:
        raise ValueError(mensaje)
    except ValueError:
        import sys
        return sys.exc_info()


def test_el_mensaje_es_entendible_y_dice_donde_está_el_log():
    tipo, valor, tb = _excepcion("no se pudo escribir el PDF")
    mensaje, _ = formatear_reporte(tipo, valor, tb,
                                   ruta_log="C:/logs/psa.log")

    assert "error inesperado" in mensaje.lower()
    assert "no se pudo escribir el PDF" in mensaje     # la causa concreta
    assert "C:/logs/psa.log" in mensaje                # dónde reportarlo
    assert "Traceback" not in mensaje                  # eso va al log, no acá


def test_el_detalle_lleva_el_traceback_y_la_version():
    tipo, valor, tb = _excepcion()
    _, detalle = formatear_reporte(tipo, valor, tb, version="1.2.3")

    assert "Traceback" in detalle
    assert "ValueError" in detalle
    assert "Versión 1.2.3" in detalle


def test_una_excepcion_sin_mensaje_igual_se_explica():
    try:
        raise RuntimeError()
    except RuntimeError:
        import sys
        tipo, valor, tb = sys.exc_info()

    mensaje, _ = formatear_reporte(tipo, valor, tb)
    assert "RuntimeError" in mensaje       # cae al nombre del tipo


def test_el_manejador_registra_y_avisa(caplog):
    vistos = []
    instalar(version="9.9.9", ruta_log="/tmp/x.log",
             mostrar_dialogo=vistos.append)

    import sys
    tipo, valor, tb = _excepcion("fallo de prueba")
    with caplog.at_level(logging.CRITICAL):
        sys.excepthook(tipo, valor, tb)

    assert vistos, "debería haber intentado mostrar el diálogo"
    assert "fallo de prueba" in vistos[0]
    assert any("no atrapada" in r.message for r in caplog.records)


def test_un_fallo_al_mostrar_el_dialogo_no_tapa_el_error(caplog):
    def dialogo_roto(_mensaje):
        raise RuntimeError("la UI ya no existe")

    instalar(mostrar_dialogo=dialogo_roto)

    import sys
    tipo, valor, tb = _excepcion("el error real")
    with caplog.at_level(logging.CRITICAL):
        sys.excepthook(tipo, valor, tb)     # no debe propagar

    assert any("el error real" in r.getMessage() for r in caplog.records)
