"""
tests/test_dispositivos.py
============================================================
Tests de la capa de dispositivos (modules/dispositivos.py).

Estos tests existen porque los drivers de impresora y escáner NO se
pueden probar en CI: no hay hardware. Al aislar el saneamiento de
capacidades y la traducción de errores en funciones puras, se puede
verificar justamente la parte que rompe en producción.

Cubren los dos fallos reales que tenía el código:
  - un driver que informa 0 DPI provocaba ZeroDivisionError
  - un driver que informa 0 de área imprimible hacía que se imprimiera
    una hoja EN BLANCO, sin ningún aviso
"""

import pytest

from modules.dispositivos import (
    A4_ALTO_IN,
    A4_ANCHO_IN,
    DPI_FALLBACK,
    DPI_RENDER_MAX,
    ErrorDispositivo,
    es_cancelacion_usuario,
    interpretar_error_wia,
    sanear_capacidades,
)

# ── Saneamiento de capacidades ────────────────────────────────────────────────

def test_driver_normal_se_respeta():
    caps = sanear_capacidades(600, 600, 4958, 7016)
    assert caps.dpi == DPI_RENDER_MAX          # capado a nuestro tope
    assert caps.ancho_px == 4958
    assert caps.alto_px == 7016
    assert not caps.fue_corregida


def test_dpi_dentro_del_tope_no_se_toca():
    caps = sanear_capacidades(200, 200, 1650, 2338)
    assert caps.dpi == 200
    assert not caps.fue_corregida


def test_dpi_cero_no_produce_division_por_cero():
    """El bug real: render_dpi=0 → zoom 0 → pixmap 0x0 → ZeroDivisionError."""
    caps = sanear_capacidades(0, 0, 4958, 7016)
    assert caps.dpi == DPI_FALLBACK
    assert caps.fue_corregida
    # Lo que importa: ya se puede dividir sin miedo
    assert caps.dpi > 0
    assert 4958 / caps.dpi > 0


def test_area_cero_no_imprime_en_blanco():
    """El otro bug: área 0 → escala 0 → hoja en blanco, sin aviso."""
    caps = sanear_capacidades(300, 300, 0, 0)
    assert caps.ancho_px == int(A4_ANCHO_IN * 300)
    assert caps.alto_px == int(A4_ALTO_IN * 300)
    assert caps.fue_corregida
    # Con estos valores la escala ya es utilizable
    assert min(caps.ancho_px / 2480, caps.alto_px / 3508) > 0.5


@pytest.mark.parametrize("dpi_x,dpi_y", [
    (-100, -100),       # negativo
    (5, 5),             # absurdamente bajo
    (999999, 999999),   # absurdamente alto
    (0, 0),
])
def test_dpi_fuera_de_rango_cae_al_valor_seguro(dpi_x, dpi_y):
    caps = sanear_capacidades(dpi_x, dpi_y, 2480, 3508)
    assert caps.dpi == DPI_FALLBACK
    assert caps.fue_corregida


def test_toma_el_mayor_de_los_dos_ejes():
    caps = sanear_capacidades(150, 300, 2480, 3508)
    assert caps.dpi == 300


def test_dpi_altisimo_se_capa_sin_marcar_correccion():
    """1200 DPI es válido; simplemente lo capamos para no volar la RAM."""
    caps = sanear_capacidades(1200, 1200, 9921, 14031)
    assert caps.dpi == DPI_RENDER_MAX
    assert not caps.fue_corregida       # no es un error del driver


@pytest.mark.parametrize("ancho,alto", [
    (-10, 100),
    (100, -10),
    (0, 3508),
    (2480, 0),
    (900_000, 3508),      # absurdo
])
def test_area_invalida_se_reemplaza_por_a4(ancho, alto):
    caps = sanear_capacidades(300, 300, ancho, alto)
    assert caps.ancho_px > 0 and caps.alto_px > 0
    assert caps.fue_corregida


def test_valores_no_numericos_no_rompen():
    """GetDeviceCaps puede devolver None si la llamada falla."""
    caps = sanear_capacidades(None, None, None, None)
    assert caps.dpi == DPI_FALLBACK
    assert caps.ancho_px > 0 and caps.alto_px > 0


def test_las_correcciones_quedan_explicadas():
    caps = sanear_capacidades(0, 0, 0, 0)
    assert len(caps.correcciones) == 2
    assert all(isinstance(c, str) and c for c in caps.correcciones)
    # Deben nombrar el valor problemático, para que el log sirva
    assert any("DPI" in c for c in caps.correcciones)


# ── Errores de dispositivo ────────────────────────────────────────────────────

def test_error_dispositivo_arma_texto_completo():
    e = ErrorDispositivo("Falló algo.", detalle="0x80004005",
                         sugerencia="Reintentá.")
    texto = e.texto_completo()
    assert "Falló algo." in texto
    assert "Reintentá." in texto
    assert "0x80004005" in texto


def test_error_dispositivo_sin_extras():
    assert ErrorDispositivo("Sólo el mensaje.").texto_completo() == \
        "Sólo el mensaje."


# ── Traducción de errores WIA ─────────────────────────────────────────────────

@pytest.mark.parametrize("crudo,esperado_en_mensaje", [
    ("Exception occurred. 0x80210006", "ocupado"),
    ("com_error 0x80210015 no device", "No se detectó"),
    ("Error 0x80210064 durante captura", "captura"),
    ("0x8021000A device not ready", "no está listo"),
    ("0x80070005 access denied", "denegó el acceso"),
    ("CoInitialize has not been called", "interno"),
])
def test_errores_wia_conocidos_se_traducen(crudo, esperado_en_mensaje):
    err = interpretar_error_wia(Exception(crudo))
    assert isinstance(err, ErrorDispositivo)
    assert esperado_en_mensaje.lower() in err.mensaje.lower()
    assert err.sugerencia                 # siempre debe decir qué hacer
    assert crudo in err.detalle           # el original queda para el log


def test_error_wia_desconocido_tiene_salida_util():
    err = interpretar_error_wia(Exception("algo rarísimo 0xDEADBEEF"))
    assert err.mensaje
    assert "disco" in err.sugerencia.lower() or "cargar" in err.sugerencia.lower()


@pytest.mark.parametrize("texto", [
    "Operation cancelled by user",
    "com_error 0x80210003",
    "USER CANCELED the dialog",
])
def test_cancelacion_del_usuario_no_es_error(texto):
    assert es_cancelacion_usuario(Exception(texto))


@pytest.mark.parametrize("texto", [
    "0x80210006 busy",
    "paper jam",
    "",
])
def test_errores_reales_no_se_confunden_con_cancelacion(texto):
    assert not es_cancelacion_usuario(Exception(texto))


# ── Degradación fuera de Windows ──────────────────────────────────────────────

def test_listar_sin_windows_devuelve_vacio():
    """En Linux/macOS la app tiene que seguir funcionando, sin dispositivos."""
    from modules.dispositivos import listar_escaneres, listar_impresoras
    assert listar_impresoras() == []
    assert listar_escaneres() == []


def test_verificaciones_explican_la_falta_de_soporte():
    import sys

    from modules.dispositivos import (
        verificar_escaneo_disponible,
        verificar_impresion_disponible,
    )
    if sys.platform == "win32":
        pytest.skip("Este test comprueba la degradación fuera de Windows")

    for verificar in (verificar_impresion_disponible, verificar_escaneo_disponible):
        with pytest.raises(ErrorDispositivo) as info:
            verificar()
        assert "Windows" in info.value.mensaje
        assert info.value.sugerencia          # debe ofrecer una alternativa


def test_com_inicializado_no_rompe_fuera_de_windows():
    from modules.dispositivos import com_inicializado

    with com_inicializado() as ok:
        assert ok is False          # no hay COM, pero tampoco excepción


# ── Flujo de adquisición con un escáner simulado ──────────────────────────────
#  Antes esto era intestable: la llamada a WIA estaba incrustada en el
#  worker de la UI. Al centralizarla se puede simular el dispositivo.

class _ImagenWIAFalsa:
    def __init__(self, ruta_a_escribir=b"PNG-falso", propiedades_ok=True):
        self._contenido = ruta_a_escribir
        self._propiedades_ok = propiedades_ok
        self.dpi_pedido = []

    def Properties(self, clave):                    # noqa: N802
        if not self._propiedades_ok:
            raise Exception("el driver no expone esta propiedad")
        imagen = self

        class Prop:
            @property
            def Value(self):                        # noqa: N802
                return 0

            @Value.setter
            def Value(self, v):                     # noqa: N802
                imagen.dpi_pedido.append((clave, v))
        return Prop()

    def SaveFile(self, ruta):                       # noqa: N802
        if self._contenido is not None:
            with open(ruta, "wb") as f:
                f.write(self._contenido)


def _simular_wia(monkeypatch, imagen):
    """Reemplaza el Dispatch de COM por un escáner de mentira."""
    class Dialogo:
        def ShowAcquireImage(self, *a):             # noqa: N802
            self.args = a
            return imagen

    dialogo = Dialogo()

    class ClienteFalso:
        @staticmethod
        def Dispatch(_nombre):                      # noqa: N802
            return dialogo

    monkeypatch.setattr("modules.dispositivos._importar_com",
                        lambda: (object(), ClienteFalso))
    return dialogo


def test_adquirir_imagen_guarda_el_archivo(tmp_path, monkeypatch):
    from modules.dispositivos import adquirir_imagen

    imagen = _ImagenWIAFalsa()
    _simular_wia(monkeypatch, imagen)

    destino = tmp_path / "escaneo.png"
    resultado = adquirir_imagen(str(destino), dpi=600)

    assert resultado == str(destino)
    assert destino.read_bytes() == b"PNG-falso"
    # Debe haber pedido 600 DPI en ambos ejes (6147 y 6148)
    assert ("6147", 600) in imagen.dpi_pedido
    assert ("6148", 600) in imagen.dpi_pedido


def test_adquirir_imagen_tolera_driver_sin_propiedad_dpi(tmp_path, monkeypatch):
    """Muchos escáneres no dejan fijar la resolución por WIA: no es fatal."""
    from modules.dispositivos import adquirir_imagen

    _simular_wia(monkeypatch, _ImagenWIAFalsa(propiedades_ok=False))
    destino = tmp_path / "escaneo.png"
    assert adquirir_imagen(str(destino)) == str(destino)
    assert destino.exists()


def test_adquirir_imagen_detecta_archivo_vacio(tmp_path, monkeypatch):
    """El escáner 'terminó bien' pero no dejó nada: no puede pasar como éxito."""
    from modules.dispositivos import adquirir_imagen

    _simular_wia(monkeypatch, _ImagenWIAFalsa(ruta_a_escribir=b""))
    with pytest.raises(ErrorDispositivo) as info:
        adquirir_imagen(str(tmp_path / "vacio.png"))
    assert "no devolvió" in info.value.mensaje


def test_adquirir_imagen_pasa_el_selector_de_dispositivo(tmp_path, monkeypatch):
    from modules.dispositivos import adquirir_imagen

    dialogo = _simular_wia(monkeypatch, _ImagenWIAFalsa())
    adquirir_imagen(str(tmp_path / "a.png"), elegir_dispositivo=True)
    # El 5º argumento de ShowAcquireImage es AlwaysSelectDevice
    assert dialogo.args[4] is True

    adquirir_imagen(str(tmp_path / "b.png"), elegir_dispositivo=False)
    assert dialogo.args[4] is False
