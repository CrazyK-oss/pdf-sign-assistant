"""
tests/conftest.py
============================================================
Piezas compartidas por los tests que necesitan Qt.

Una sola QApplication para toda la sesión
-----------------------------------------
Qt no admite dos QApplication vivas, pero el problema real es más sutil:
si cada módulo de test crea la suya en un fixture, al terminar ese módulo
Python recolecta el objeto, Qt **destruye todos los QObject que quedaban
vivos** y se lleva puesto `modules.theme.theme_signals`, que se crea al
importar el módulo y no tiene dueño. El módulo siguiente entonces falla
con:

    RuntimeError: wrapped C/C++ object of type _ThemeSignals has been deleted

…y no falla al correr ese archivo solo, sólo cuando corre la suite
entera. Por eso la instancia se guarda además en una variable global: la
referencia del fixture no alcanza para impedir la recolección.
"""

from __future__ import annotations

import os

import pytest

# Sin pantalla, Qt no arranca. Se define antes de que nadie importe PyQt6
# y sólo si no venía puesto, para no pisar lo que haya elegido el CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

#: Referencia global a la QApplication. No es decorativa: ver el docstring.
_APP = None


@pytest.fixture(scope="session")
def qapp():
    """La QApplication compartida por toda la sesión de tests."""
    global _APP

    pytest.importorskip("PyQt6", reason="Necesita las dependencias de la app")
    from PyQt6.QtWidgets import QApplication

    if _APP is None:
        _APP = QApplication.instance() or QApplication(["tests"])
    return _APP
