"""
tests/test_escaner_lote.py
============================================================
Tests del escaneo por lote desde el alimentador (ADF) y del dúplex.

Por qué hay un escáner falso acá
--------------------------------
El bucle del lote no se puede probar de otra forma: no hay hardware en CI,
y es justo la parte donde un error cuesta caro. Se le pide una hoja tras
otra al aparato hasta que contesta "no hay más papel", y esa condición de
salida es un CÓDIGO DE ERROR, no un valor de retorno. Confundirlo —como
estaba— hace que un lote de 20 hojas termine como si el usuario hubiera
cancelado.

El doble implementa la misma forma que expone WIA por COM: un manager con
DeviceInfos indexados desde 1, un dispositivo con Properties e Items, y un
Transfer que devuelve algo con SaveFile. Es la superficie que toca el
código de verdad, ni más ni menos.

Lo que estos tests NO prueban: que el driver real se comporte así. Eso
sólo lo dice la impresora cuando llegue. Lo que sí prueban es que, dado
ese comportamiento, nuestra parte hace lo correcto.

Python puro: corren en el CI liviano.
"""

from __future__ import annotations

import pytest

from modules.dispositivos import (
    LOTE_MAX_PAGINAS,
    WIA_CAP_DETECT_FEED,
    WIA_CAP_DUPLEX,
    WIA_CAP_FEEDER,
    WIA_CAP_FLATBED,
    WIA_DPS_DOCUMENT_HANDLING_SELECT,
    WIA_DPS_PAGES,
    WIA_EST_FEED_READY,
    WIA_SEL_DUPLEX,
    WIA_SEL_FEEDER,
    WIA_SEL_FLATBED,
    ErrorDispositivo,
    ErrorLoteParcial,
    adquirir_lote,
    bits_de_origen,
    configurar_lote,
    interpretar_capacidades,
)

# ═══════════════════════════════════════════════════════════════════════════════
#  Interpretación de las capacidades
# ═══════════════════════════════════════════════════════════════════════════════

def test_un_escaner_solo_de_cristal():
    cap = interpretar_capacidades(WIA_CAP_FLATBED)
    assert cap.cristal and not cap.alimentador and not cap.duplex
    assert not cap.por_lote
    assert cap.descripcion() == "Sólo cristal"


def test_un_escaner_con_alimentador_simple():
    cap = interpretar_capacidades(WIA_CAP_FLATBED | WIA_CAP_FEEDER)
    assert cap.alimentador and cap.cristal and not cap.duplex
    assert cap.por_lote
    assert cap.descripcion() == "Con alimentador"


def test_un_escaner_con_alimentador_duplex():
    """La máquina que va a comprar el cliente."""
    cap = interpretar_capacidades(
        WIA_CAP_FLATBED | WIA_CAP_FEEDER | WIA_CAP_DUPLEX)
    assert cap.alimentador and cap.duplex and cap.por_lote
    assert cap.descripcion() == "Alimentador dúplex"


def test_el_duplex_sin_alimentador_se_descarta():
    """Algunos drivers publican el bit igual. Creerles deja habilitado un
    modo que no se puede usar: el dúplex son las dos caras de la hoja que
    PASA por el alimentador, sin alimentador no significa nada."""
    cap = interpretar_capacidades(WIA_CAP_FLATBED | WIA_CAP_DUPLEX)
    assert not cap.duplex


def test_un_escaner_que_no_publica_nada_se_asume_de_cristal():
    """Los drivers viejos rara vez publican estas propiedades. Suponer que
    hay alimentador deja al usuario apretando un botón que da error."""
    cap = interpretar_capacidades(0, 0, conocidas=False)
    assert cap.cristal and not cap.alimentador and not cap.duplex
    assert not cap.conocidas
    assert cap.descripcion() == "Escáner listo"


def test_solo_alimentador_sin_bit_de_cristal():
    """Un escáner de documentos puro no tiene cristal, y está bien."""
    cap = interpretar_capacidades(WIA_CAP_FEEDER)
    assert cap.alimentador and not cap.cristal


def test_deteccion_de_papel():
    con_papel = interpretar_capacidades(
        WIA_CAP_FEEDER | WIA_CAP_DETECT_FEED, WIA_EST_FEED_READY)
    assert con_papel.detecta_papel and con_papel.hay_papel

    vacio = interpretar_capacidades(WIA_CAP_FEEDER | WIA_CAP_DETECT_FEED, 0)
    assert vacio.detecta_papel and not vacio.hay_papel


# ═══════════════════════════════════════════════════════════════════════════════
#  Bits que se le piden al driver
# ═══════════════════════════════════════════════════════════════════════════════

def test_bits_de_cristal():
    assert bits_de_origen(alimentador=False, duplex=False) == WIA_SEL_FLATBED


def test_bits_de_alimentador_simple():
    assert bits_de_origen(alimentador=True, duplex=False) == WIA_SEL_FEEDER


def test_bits_de_alimentador_duplex():
    esperado = WIA_SEL_FEEDER | WIA_SEL_DUPLEX
    assert bits_de_origen(alimentador=True, duplex=True) == esperado


def test_pedir_duplex_sin_alimentador_es_un_error_de_programacion():
    """Mandado al driver se traduce en un com_error incomprensible o,
    peor, en que escanee sólo la primera cara sin decir nada."""
    with pytest.raises(ValueError, match="alimentador"):
        bits_de_origen(alimentador=False, duplex=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Escáner falso
# ═══════════════════════════════════════════════════════════════════════════════

class ErrorCom(Exception):
    """Se parece a lo que tira pywin32: el código va en el texto."""


def sin_papel() -> ErrorCom:
    return ErrorCom("com_error (-2145386493, 'Excepción', "
                    "'0x80210003 WIA_ERROR_PAPER_EMPTY')")


def atasco() -> ErrorCom:
    return ErrorCom("com_error 0x80210002 WIA_ERROR_PAPER_JAM")


class _Propiedad:
    def __init__(self, almacen, clave):
        self._almacen, self._clave = almacen, clave

    @property
    def Value(self):                                     # noqa: N802 (API COM)
        if self._clave not in self._almacen:
            raise ErrorCom(f"propiedad {self._clave} no publicada")
        return self._almacen[self._clave]

    @Value.setter
    def Value(self, valor):                              # noqa: N802
        if self._clave in self._almacen.rechazadas:
            raise ErrorCom(f"el driver rechaza {self._clave}")
        self._almacen[self._clave] = valor


class _Almacen(dict):
    def __init__(self, *a, rechazadas=(), **kw):
        super().__init__(*a, **kw)
        self.rechazadas = set(rechazadas)


class _Imagen:
    def __init__(self, contenido: bytes):
        self._contenido = contenido

    def SaveFile(self, ruta):                            # noqa: N802
        with open(ruta, "wb") as f:
            f.write(self._contenido)


class _Item:
    def __init__(self, escaner):
        self._escaner = escaner
        self._props = _Almacen()

    def Properties(self, clave):                         # noqa: N802
        return _Propiedad(self._props, str(clave))

    def Transfer(self, _formato):                        # noqa: N802
        return self._escaner._siguiente()


class _Dispositivo:
    def __init__(self, escaner):
        self._escaner = escaner

    def Properties(self, clave):                         # noqa: N802
        return _Propiedad(self._escaner.props, str(clave))

    def Items(self, _n):                                 # noqa: N802
        return _Item(self._escaner)


class _Info:
    def __init__(self, escaner, device_id, tipo=1):
        self._escaner, self.DeviceID, self.Type = escaner, device_id, tipo

    def Connect(self):                                   # noqa: N802
        return _Dispositivo(self._escaner)


class _Infos:
    def __init__(self, infos):
        self._infos = infos
        self.Count = len(infos)

    def __call__(self, i):
        return self._infos[i - 1]                        # WIA indexa desde 1


class EscanerFalso:
    """Un escáner de mentira con la forma que expone WIA por COM.

    `hojas` es cuántas páginas hay en la bandeja; `falla_en` permite
    inyectar un atasco en la hoja N (1-based) para probar que lo ya
    escaneado no se tira.
    """

    def __init__(self, hojas=3, *, falla_en=None, rechaza=(), device_id="X1"):
        self.hojas = hojas
        self.falla_en = falla_en
        self.entregadas = 0
        self.props = _Almacen(rechazadas=rechaza)
        self.device_id = device_id

    def _siguiente(self):
        self.entregadas += 1
        if self.falla_en is not None and self.entregadas == self.falla_en:
            raise atasco()
        if self.entregadas > self.hojas:
            raise sin_papel()
        return _Imagen(b"PNG-falso-" + str(self.entregadas).encode())

    # Lo que ve el código de producción
    def Dispatch(self, nombre):                          # noqa: N802
        assert nombre == "WIA.DeviceManager", nombre
        return self

    @property
    def DeviceInfos(self):                               # noqa: N802
        return _Infos([_Info(self, self.device_id)])


@pytest.fixture
def escaner(monkeypatch):
    """Instala el escáner falso en lugar del COM de Windows."""
    falso = EscanerFalso()

    def _fake_com():
        return (None, falso)

    monkeypatch.setattr("modules.dispositivos._importar_com", _fake_com)
    return falso


@pytest.fixture
def destino(tmp_path):
    return lambda n: str(tmp_path / f"pagina_{n:03d}.png")


# ═══════════════════════════════════════════════════════════════════════════════
#  Configuración del trabajo
# ═══════════════════════════════════════════════════════════════════════════════

def test_configurar_lote_pide_alimentador_y_todas_las_paginas(escaner):
    configurar_lote(_Dispositivo(escaner), alimentador=True, duplex=False)
    assert escaner.props[str(WIA_DPS_DOCUMENT_HANDLING_SELECT)] == WIA_SEL_FEEDER
    assert escaner.props[str(WIA_DPS_PAGES)] == 0        # 0 = todas


def test_configurar_lote_duplex(escaner):
    configurar_lote(_Dispositivo(escaner), alimentador=True, duplex=True)
    assert (escaner.props[str(WIA_DPS_DOCUMENT_HANDLING_SELECT)]
            == WIA_SEL_FEEDER | WIA_SEL_DUPLEX)


def test_un_driver_que_rechaza_las_propiedades_no_frena_el_escaneo():
    """Muchos aceptan sólo un subconjunto. Fallar acá impediría escanear en
    aparatos donde el trabajo habría salido bien con los valores por
    defecto del driver."""
    terco = EscanerFalso(rechaza=[str(WIA_DPS_DOCUMENT_HANDLING_SELECT),
                                  str(WIA_DPS_PAGES)])
    configurar_lote(_Dispositivo(terco), alimentador=True, duplex=True)
    assert not terco.props                               # no guardó nada, y no reventó


# ═══════════════════════════════════════════════════════════════════════════════
#  El bucle del lote
# ═══════════════════════════════════════════════════════════════════════════════

def test_escanea_todas_las_hojas_del_taco(escaner, destino):
    escaner.hojas = 5
    rutas = adquirir_lote(destino, alimentador=True)
    assert len(rutas) == 5
    assert all(open(r, "rb").read() for r in rutas)


def test_el_fin_de_papel_termina_el_lote_sin_error(escaner, destino):
    """Es LA condición de salida, y llega como código de error. Antes
    estaba clasificada como cancelación del usuario."""
    escaner.hojas = 2
    rutas = adquirir_lote(destino, alimentador=True)
    assert len(rutas) == 2
    # Se le pidió una de más: así es como se entera de que se terminó
    assert escaner.entregadas == 3


def test_una_bandeja_vacia_sí_es_un_error(escaner, destino):
    """Sin papel Y sin ninguna página traída: el usuario apretó escanear
    con la bandeja vacía y merece que se lo digan."""
    escaner.hojas = 0
    with pytest.raises(ErrorDispositivo, match="No hay papel"):
        adquirir_lote(destino, alimentador=True)


def test_las_paginas_se_avisan_a_medida_que_llegan(escaner, destino):
    """La pantalla las muestra sin esperar a que termine el taco: con 20
    hojas, esperar al final son minutos mirando una barra."""
    escaner.hojas = 4
    vistas = []
    adquirir_lote(destino, alimentador=True,
                  al_llegar=lambda ruta, n: vistas.append((n, ruta)))
    assert [n for n, _ in vistas] == [1, 2, 3, 4]


def test_un_atasco_a_mitad_conserva_lo_ya_escaneado(escaner, destino):
    """Un atasco en la hoja 18 de 20 no puede obligar a rehacer las 17 que
    ya estaban bien."""
    escaner.hojas = 10
    escaner.falla_en = 4                      # revienta al pedir la cuarta
    with pytest.raises(ErrorLoteParcial) as e:
        adquirir_lote(destino, alimentador=True)

    assert len(e.value.rutas) == 3
    assert "atasc" in e.value.mensaje.lower()
    assert all(open(r, "rb").read() for r in e.value.rutas)


def test_un_atasco_en_la_primera_hoja_es_un_error_normal(escaner, destino):
    """Sin páginas rescatadas no hay nada parcial que reportar."""
    escaner.hojas = 10
    escaner.falla_en = 1
    with pytest.raises(ErrorDispositivo) as e:
        adquirir_lote(destino, alimentador=True)
    assert not isinstance(e.value, ErrorLoteParcial)


def test_se_puede_cancelar_entre_paginas(escaner, destino):
    """Un taco de 50 hojas tiene que poder frenarse sin esperar al final."""
    escaner.hojas = 50
    rutas = adquirir_lote(destino, alimentador=True,
                          cancelado=lambda: escaner.entregadas >= 3)
    assert len(rutas) == 3


def test_hay_un_tope_de_cordura(escaner, destino):
    """Si un driver nunca avisa que se quedó sin papel —los hay— el bucle
    llenaría el disco."""
    escaner.hojas = 10_000
    rutas = adquirir_lote(destino, alimentador=True, maximo=7)
    assert len(rutas) == 7
    assert LOTE_MAX_PAGINAS > 0


def test_el_lote_configura_el_dispositivo_antes_de_transferir(escaner, destino):
    escaner.hojas = 1
    adquirir_lote(destino, alimentador=True, duplex=True)
    assert (escaner.props[str(WIA_DPS_DOCUMENT_HANDLING_SELECT)]
            == WIA_SEL_FEEDER | WIA_SEL_DUPLEX)


def test_cada_pagina_va_a_su_propio_archivo(escaner, destino):
    """Un destino fijo dejaría una sola página, la última, sin avisar."""
    escaner.hojas = 3
    rutas = adquirir_lote(destino, alimentador=True)
    assert len(set(rutas)) == 3


def test_sin_escaner_conectado_lo_dice(monkeypatch, destino):
    vacio = EscanerFalso()
    monkeypatch.setattr(type(vacio), "DeviceInfos",
                        property(lambda self: _Infos([])))
    monkeypatch.setattr("modules.dispositivos._importar_com",
                        lambda: (None, vacio))
    with pytest.raises(ErrorDispositivo, match="ningún escáner"):
        adquirir_lote(destino, alimentador=True)
