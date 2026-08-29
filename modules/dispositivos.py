"""
modules/dispositivos.py
============================================================
Capa única de acceso a impresoras y escáneres.

Por qué existe
--------------
No se pueden "unificar drivers": los distribuye el fabricante y los
instala Windows. WIA (escáner) y GDI (impresión) YA SON la capa de
unificación que provee el sistema, y es la que usa esta app.

Lo que sí se unifica es nuestro lado: todo el acceso a dispositivos
pasa por acá, en vez de tener llamadas a win32 desparramadas por las
fases. Eso da tres cosas:

  1. Un único lugar donde validar lo que devuelven los drivers.
  2. Errores con mensaje entendible y sugerencia concreta, en vez de
     un com_error crudo en la cara del usuario.
  3. Lógica testeable: el saneamiento de capacidades es una función
     pura, así que se puede probar sin impresora (y de hecho es la
     única forma de probarlo en CI).

Los drivers mienten
-------------------
Este módulo asume que un driver puede devolver cualquier cosa:
  - 0 DPI (impresoras virtuales, drivers genéricos) → antes producía
    un ZeroDivisionError y la impresión reventaba
  - 0 de área imprimible → antes daba escala 0 y se imprimía una hoja
    EN BLANCO sin avisar
  - valores absurdos (100000 DPI) que harían explotar la memoria
Todos esos casos se corrigen y se dejan anotados en el log.
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ── Límites de cordura para lo que informa un driver ──────────────────────────
DPI_MIN = 50
DPI_MAX = 2400
DPI_FALLBACK = 300          # el valor sensato si el driver no dice nada útil
DPI_RENDER_MAX = 300        # tope propio, para no armar bitmaps gigantes
PX_MAX = 60_000             # ~50 cm a 3000 dpi: más que eso es un error

# A4 en pulgadas, para deducir el área imprimible cuando el driver no la da
A4_ANCHO_IN = 8.27
A4_ALTO_IN = 11.69

# DPI de reintento cuando la impresora rechaza un bitmap grande
DPI_REINTENTOS = (200, 150)

# Tipo de dispositivo WIA
WIA_TIPO_ESCANER = 1

# ── WIA: propiedades del manejo de documentos ────────────────────────────────
# Son las que gobiernan el alimentador automático (ADF) y el dúplex. Los
# números son de la especificación de WIA, no inventados: los drivers los
# publican con estos IDs y no con nombres.
WIA_DPS_DOCUMENT_HANDLING_CAPABILITIES = 3086   # qué sabe hacer el aparato
WIA_DPS_DOCUMENT_HANDLING_STATUS       = 3087   # cómo está AHORA
WIA_DPS_DOCUMENT_HANDLING_SELECT       = 3088   # qué le pedimos que use
WIA_DPS_PAGES                          = 3096   # cuántas hojas; 0 = todas

# Bits de CAPABILITIES: qué puede hacer el escáner.
WIA_CAP_FEEDER   = 0x001        # tiene alimentador
WIA_CAP_FLATBED  = 0x002        # tiene cristal
WIA_CAP_DUPLEX   = 0x004        # escanea las dos caras de una pasada
WIA_CAP_DETECT_FEED = 0x020     # sabe si hay papel cargado
WIA_CAP_DETECT_DUP  = 0x040

# Bits de STATUS: cómo está el escáner en este momento.
WIA_EST_FEED_READY = 0x001      # hay papel en el alimentador
WIA_EST_FLAT_READY = 0x002
WIA_EST_DUP_READY  = 0x004

# Bits de SELECT: lo que se le pide para el trabajo.
WIA_SEL_FEEDER  = 0x001
WIA_SEL_FLATBED = 0x002
WIA_SEL_DUPLEX  = 0x004

#: Pedirle 0 páginas a WIA significa "todas las que haya en el alimentador".
WIA_TODAS_LAS_PAGINAS = 0

#: Tope de seguridad del lote. Si un driver nunca avisa que se quedó sin
#: papel —los hay—, sin esto el bucle escanea para siempre y llena el disco.
LOTE_MAX_PAGINAS = 500

# ── WIA: códigos de error que importan con alimentador ───────────────────────
# Con cristal casi no aparecen; con ADF son parte del funcionamiento normal.
WIA_ERROR_PAPER_JAM   = "0x80210002"
WIA_ERROR_PAPER_EMPTY = "0x80210003"    # NO es una cancelación: es fin de papel
WIA_ERROR_PAPER_PROBLEM = "0x80210004"
WIA_ERROR_COVER_OPEN  = "0x80210016"


class ErrorDispositivo(Exception):
    """Error de impresora o escáner con texto apto para mostrar.

    Lleva el detalle técnico aparte, para que el diálogo muestre algo
    entendible y el log conserve la causa real.
    """

    def __init__(self, mensaje: str, detalle: str = "", sugerencia: str = ""):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle = detalle
        self.sugerencia = sugerencia

    def texto_completo(self) -> str:
        partes = [self.mensaje]
        if self.sugerencia:
            partes.append(f"\n{self.sugerencia}")
        if self.detalle:
            partes.append(f"\nDetalle técnico:\n{self.detalle}")
        return "\n".join(partes)


# ═══════════════════════════════════════════════════════════════════════════════
#  Disponibilidad de la plataforma
# ═══════════════════════════════════════════════════════════════════════════════

def _importar_win32():
    """Devuelve (win32con, win32ui, win32print) o None si no están.

    Se importa acá adentro para que el módulo entero se pueda importar
    (y testear) en Linux o macOS.
    """
    if sys.platform != "win32":
        return None
    try:
        import win32con
        import win32print
        import win32ui
        return win32con, win32ui, win32print
    except ImportError:
        return None


def soporte_windows() -> bool:
    """True si se puede hablar con impresoras y escáneres de Windows."""
    return _importar_win32() is not None


def _importar_com():
    if sys.platform != "win32":
        return None
    try:
        import pythoncom
        import win32com.client
        return pythoncom, win32com.client
    except ImportError:
        return None


@contextmanager
def com_inicializado():
    """Inicializa COM para el hilo actual y lo libera al salir.

    IMPRESCINDIBLE al usar WIA desde un QThread: pywin32 NO inicializa
    COM automáticamente en hilos nuevos, y sin esto toda llamada falla
    con "CoInitialize has not been called". El síntoma que veía el
    usuario era un error genérico del escáner que lo mandaba a revisar
    cables, cuando el problema estaba de este lado.

    Se usa STA (apartamento de un solo hilo) porque WIA muestra
    diálogos: es el modelo que corresponde para COM con interfaz.
    """
    com = _importar_com()
    if com is None:
        yield False
        return

    pythoncom, _ = com
    inicializado = False
    try:
        pythoncom.CoInitialize()
        inicializado = True
    except Exception as e:                           # noqa: BLE001
        # Si otro componente ya lo inicializó en modo distinto, seguimos:
        # las llamadas van a funcionar igual dentro de ese apartamento.
        log.debug("CoInitialize devolvió %s (puede ser inofensivo)", e)
    try:
        yield True
    finally:
        if inicializado:
            try:
                pythoncom.CoUninitialize()
            except Exception:                        # noqa: BLE001
                pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Impresión
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CapacidadesImpresion:
    """Lo que dice la impresora, ya validado y usable sin miedo."""

    dpi: int
    ancho_px: int
    alto_px: int
    correcciones: list[str] = field(default_factory=list)

    @property
    def fue_corregida(self) -> bool:
        return bool(self.correcciones)


def sanear_capacidades(dpi_x: int, dpi_y: int,
                       ancho_px: int, alto_px: int) -> CapacidadesImpresion:
    """Convierte lo que informa el driver en valores utilizables.

    Función PURA: no toca Windows, así que se puede testear entera sin
    una impresora conectada. Es la que evita los dos fallos reales:
      - DPI 0  → ZeroDivisionError al calcular el zoom del render
      - área 0 → escala 0 → hoja impresa en blanco, sin ningún aviso
    """
    correcciones: list[str] = []

    # ── DPI ──────────────────────────────────────────────────────────
    try:
        dpi = max(int(dpi_x or 0), int(dpi_y or 0))
    except (TypeError, ValueError):
        dpi = 0

    if not (DPI_MIN <= dpi <= DPI_MAX):
        correcciones.append(
            f"La impresora informó {dpi} DPI, fuera de lo razonable; "
            f"se usan {DPI_FALLBACK}.")
        dpi = DPI_FALLBACK

    dpi = min(dpi, DPI_RENDER_MAX)

    # ── Área imprimible ──────────────────────────────────────────────
    try:
        ancho = int(ancho_px or 0)
        alto = int(alto_px or 0)
    except (TypeError, ValueError):
        ancho = alto = 0

    if ancho <= 0 or alto <= 0 or ancho > PX_MAX or alto > PX_MAX:
        correcciones.append(
            f"La impresora informó un área de {ancho}x{alto} px; "
            "se asume una hoja A4.")
        ancho = int(A4_ANCHO_IN * dpi)
        alto = int(A4_ALTO_IN * dpi)

    return CapacidadesImpresion(dpi=dpi, ancho_px=ancho, alto_px=alto,
                                correcciones=correcciones)


def listar_impresoras() -> list[str]:
    """Nombres de las impresoras instaladas. Lista vacía si no hay ninguna."""
    mods = _importar_win32()
    if mods is None:
        return []
    _, _, win32print = mods
    try:
        nivel = 2
        return [
            imp["pPrinterName"]
            for imp in win32print.EnumPrinters(
                win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
                None, nivel)
        ]
    except Exception as e:                           # noqa: BLE001
        log.warning("No se pudieron enumerar las impresoras: %s", e)
        return []


def impresora_predeterminada() -> str:
    mods = _importar_win32()
    if mods is None:
        return ""
    _, _, win32print = mods
    try:
        return win32print.GetDefaultPrinter() or ""
    except Exception:                                # noqa: BLE001
        return ""


def verificar_impresion_disponible() -> None:
    """Lanza ErrorDispositivo si no se puede imprimir. No devuelve nada."""
    if sys.platform != "win32":
        raise ErrorDispositivo(
            "La impresión directa sólo está disponible en Windows.",
            sugerencia="El resto de la aplicación funciona igual en "
                       "cualquier sistema.")
    if _importar_win32() is None:
        raise ErrorDispositivo(
            "Faltan los componentes de Windows para imprimir.",
            sugerencia="Instalalos con:\n    pip install pywin32")
    if not listar_impresoras():
        raise ErrorDispositivo(
            "No hay ninguna impresora instalada en este equipo.",
            sugerencia="Agregá una desde Configuración → Bluetooth y "
                       "dispositivos → Impresoras y escáneres.")


@contextmanager
def contexto_impresora(nombre: str):
    """Abre el DC de la impresora y garantiza que se libere.

    Un DC que queda abierto se lleva un recurso del sistema hasta que
    se cierra la aplicación; con varios trabajos seguidos, eso termina
    en errores de "no hay memoria" que no tienen nada que ver con la RAM.
    """
    mods = _importar_win32()
    if mods is None:
        raise ErrorDispositivo("No hay soporte de impresión en este sistema.")
    _, win32ui, _ = mods

    hdc = None
    try:
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(nombre)
    except Exception as e:                           # noqa: BLE001
        if hdc is not None:
            try:
                hdc.DeleteDC()
            except Exception:                        # noqa: BLE001
                pass
        raise ErrorDispositivo(
            f"No se pudo conectar con la impresora «{nombre}».",
            detalle=str(e),
            sugerencia="Verificá que esté encendida, conectada y que no "
                       "tenga trabajos con error en la cola.") from e

    try:
        yield hdc
    finally:
        try:
            hdc.DeleteDC()
        except Exception:                            # noqa: BLE001
            pass


def leer_capacidades(hdc) -> CapacidadesImpresion:
    """Lee y sanea las capacidades del DC de una impresora."""
    mods = _importar_win32()
    if mods is None:
        return sanear_capacidades(0, 0, 0, 0)
    win32con, _, _ = mods

    def cap(indice: int) -> int:
        try:
            return int(hdc.GetDeviceCaps(indice))
        except Exception as e:                       # noqa: BLE001
            log.warning("GetDeviceCaps(%s) falló: %s", indice, e)
            return 0

    caps = sanear_capacidades(
        cap(win32con.LOGPIXELSX), cap(win32con.LOGPIXELSY),
        cap(win32con.HORZRES), cap(win32con.VERTRES),
    )
    for nota in caps.correcciones:
        log.warning("Capacidades de impresora corregidas: %s", nota)
    return caps


# ═══════════════════════════════════════════════════════════════════════════════
#  Escaneo (WIA)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DispositivoEscaner:
    id: str
    nombre: str

    def __str__(self) -> str:
        return self.nombre or self.id


def listar_escaneres() -> list[DispositivoEscaner]:
    """Escáneres visibles para WIA. Lista vacía si no hay o si falla.

    Se usa para distinguir "no tenés escáner conectado" de "el escáner
    dio error", que para el usuario son dos problemas muy distintos.
    """
    com = _importar_com()
    if com is None:
        return []

    dispositivos: list[DispositivoEscaner] = []
    try:
        with com_inicializado() as ok:
            if not ok:
                return []
            _, cliente = com
            manager = cliente.Dispatch("WIA.DeviceManager")
            infos = manager.DeviceInfos
            # WIA indexa desde 1, no desde 0
            for i in range(1, infos.Count + 1):
                try:
                    info = infos(i)
                    if int(info.Type) != WIA_TIPO_ESCANER:
                        continue
                    nombre = ""
                    try:
                        nombre = str(info.Properties("Name").Value)
                    except Exception:                # noqa: BLE001
                        pass
                    dispositivos.append(
                        DispositivoEscaner(id=str(info.DeviceID), nombre=nombre))
                except Exception as e:               # noqa: BLE001
                    log.debug("Dispositivo WIA %d ilegible: %s", i, e)
    except Exception as e:                           # noqa: BLE001
        log.warning("No se pudieron enumerar los escáneres: %s", e)
    return dispositivos


@dataclass(frozen=True)
class CapacidadesEscaner:
    """Qué sabe hacer el escáner y cómo está en este momento.

    Se lee de las propiedades WIA del dispositivo. Un driver puede no
    publicarlas —los de escáneres viejos rara vez lo hacen—, y en ese caso
    se asume lo conservador: sólo cristal, una hoja por vez. Suponer que
    hay alimentador cuando no lo hay deja al usuario apretando un botón
    que devuelve error.
    """

    alimentador: bool = False
    cristal: bool = True
    duplex: bool = False
    #: El aparato sabe decir si tiene papel cargado. Sin esto no se puede
    #: avisar "cargá el taco" antes de empezar: hay que intentar y fallar.
    detecta_papel: bool = False
    #: Estado actual, sólo válido si detecta_papel.
    hay_papel: bool = False
    #: True si las propiedades se pudieron leer de verdad. Si es False, lo
    #: de arriba son valores por defecto y no hechos.
    conocidas: bool = False

    @property
    def por_lote(self) -> bool:
        """Si tiene sentido ofrecer "escanear todo el taco de corrido"."""
        return self.alimentador

    def descripcion(self) -> str:
        """Texto corto para el chip de la pantalla."""
        if not self.conocidas:
            return "Escáner listo"
        if self.alimentador and self.duplex:
            return "Alimentador dúplex"
        if self.alimentador:
            return "Con alimentador"
        return "Sólo cristal"


def interpretar_capacidades(bits_capacidad: int, bits_estado: int = 0, *,
                            conocidas: bool = True) -> CapacidadesEscaner:
    """Traduce los bits que publica WIA a algo con nombre.

    Función pura y separada del acceso al dispositivo a propósito: es la
    parte que se puede equivocar (un bit mal leído convierte un escáner
    dúplex en uno simple) y la única que se puede probar sin hardware.

    Un aparato sin ningún bit de origen declarado se toma como "cristal":
    algo tiene que tener, y es lo que ya se venía asumiendo.
    """
    cap = int(bits_capacidad or 0)
    est = int(bits_estado or 0)

    alimentador = bool(cap & WIA_CAP_FEEDER)
    cristal = bool(cap & WIA_CAP_FLATBED) or not alimentador

    return CapacidadesEscaner(
        alimentador=alimentador,
        cristal=cristal,
        # El dúplex sin alimentador no significa nada: son las dos caras de
        # la hoja que PASA por el alimentador. Un driver puede publicar el
        # bit igual, y creerle deja un modo que no se puede usar.
        duplex=bool(cap & WIA_CAP_DUPLEX) and alimentador,
        detecta_papel=bool(cap & WIA_CAP_DETECT_FEED),
        hay_papel=bool(est & WIA_EST_FEED_READY),
        conocidas=conocidas,
    )


def _leer_propiedad(objeto, propiedad, defecto=0):
    """Lee una propiedad WIA sin romperse si el driver no la publica.

    Casi ningún driver publica todas: pedir una que no está tira com_error,
    y eso no es un fallo, es lo normal.
    """
    try:
        return objeto.Properties(str(propiedad)).Value
    except Exception:                                # noqa: BLE001
        log.debug("El dispositivo no publica la propiedad %s", propiedad)
        return defecto


def capacidades_escaner(id_dispositivo: str = "") -> CapacidadesEscaner:
    """Capacidades del escáner indicado, o del primero que haya.

    Nunca lanza: si algo falla devuelve capacidades conservadoras con
    `conocidas=False`. Es una consulta para decidir qué botones habilitar,
    y no poder responderla no debería impedir escanear como siempre.
    """
    com = _importar_com()
    if com is None:
        return CapacidadesEscaner()

    try:
        with com_inicializado() as ok:
            if not ok:
                return CapacidadesEscaner()
            _, cliente = com
            manager = cliente.Dispatch("WIA.DeviceManager")
            infos = manager.DeviceInfos
            for i in range(1, infos.Count + 1):        # WIA indexa desde 1
                info = infos(i)
                if int(info.Type) != WIA_TIPO_ESCANER:
                    continue
                if id_dispositivo and str(info.DeviceID) != id_dispositivo:
                    continue
                dispositivo = info.Connect()
                return interpretar_capacidades(
                    _leer_propiedad(dispositivo,
                                    WIA_DPS_DOCUMENT_HANDLING_CAPABILITIES),
                    _leer_propiedad(dispositivo,
                                    WIA_DPS_DOCUMENT_HANDLING_STATUS),
                )
    except Exception as e:                           # noqa: BLE001
        log.warning("No se pudieron leer las capacidades del escáner: %s", e)
    return CapacidadesEscaner()


def verificar_escaneo_disponible() -> None:
    """Lanza ErrorDispositivo si no se puede escanear."""
    if sys.platform != "win32":
        raise ErrorDispositivo(
            "El escaneo directo sólo está disponible en Windows.",
            sugerencia="Podés cargar las imágenes desde el disco o "
                       "arrastrarlas a la ventana.")
    if _importar_com() is None:
        raise ErrorDispositivo(
            "Faltan los componentes de Windows para escanear.",
            sugerencia="Instalalos con:\n    pip install pywin32\n\n"
                       "Después reiniciá la aplicación.")
    if not listar_escaneres():
        raise ErrorDispositivo(
            "No se detectó ningún escáner conectado.",
            sugerencia="Verificá que esté encendido y conectado, y que "
                       "Windows lo reconozca en Configuración → "
                       "Impresoras y escáneres.\n\n"
                       "También podés cargar la imagen desde el disco.")


def adquirir_imagen(ruta_destino: str, *, dpi: int = 600,
                    elegir_dispositivo: bool = False) -> str:
    """Abre el diálogo de digitalización de WIA y guarda la imagen.

    Es la ÚNICA llamada al escáner de toda la aplicación. Debe correr en
    un hilo con COM inicializado (usar com_inicializado()).

    Lanza ErrorDispositivo con mensaje traducido, o deja pasar la
    excepción original de cancelación para que el llamador la reconozca
    con es_cancelacion_usuario().
    """
    com = _importar_com()
    if com is None:
        raise ErrorDispositivo(
            "No se pudieron cargar los componentes de Windows para escanear.",
            sugerencia="Instalalos con:  pip install pywin32")

    import os

    _, cliente = com
    wia = cliente.Dispatch("WIA.CommonDialog")

    # ShowAcquireImage(
    #   DeviceType:         1 = Scanner
    #   Intent:             1 = Color
    #   Bias:               4 = MaximumQuality
    #   FormatID:           PNG sin pérdida
    #   AlwaysSelectDevice: mostrar el selector de escáner
    #   UseCommonUI:        True  (diálogo completo de WIA)
    #   CancelError:        True  (excepción si el usuario cancela)
    # )
    imagen = wia.ShowAcquireImage(
        1, 1, 4,
        "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}",   # PNG
        bool(elegir_dispositivo), True, True,
    )

    # Algunos escáneres exponen la resolución como propiedad WIA
    # (6147 = horizontal, 6148 = vertical). Si el driver no la publica,
    # el usuario ya pudo elegirla en el diálogo.
    for propiedad in ("6147", "6148"):
        try:
            imagen.Properties(propiedad).Value = int(dpi)
        except Exception:                            # noqa: BLE001
            log.debug("El escáner no admite fijar la propiedad %s", propiedad)

    imagen.SaveFile(ruta_destino)

    if not os.path.exists(ruta_destino) or os.path.getsize(ruta_destino) == 0:
        raise ErrorDispositivo(
            "El escáner no devolvió ninguna imagen.",
            sugerencia="Revisá que el papel esté bien colocado y volvé "
                       "a intentar.")
    return ruta_destino


#: Formato PNG para las transferencias WIA (sin pérdida).
WIA_FORMATO_PNG = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"

#: Propiedades de resolución del ítem de escaneo.
WIA_IPS_XRES = 6147
WIA_IPS_YRES = 6148


class ErrorLoteParcial(ErrorDispositivo):
    """Falló a mitad de un lote, pero algunas páginas se alcanzaron a leer.

    Existe porque tirarlas sería lo peor que puede hacer la aplicación en
    ese momento: un atasco en la hoja 18 de 20 obligaría a rehacer las 17
    que ya estaban bien.
    """

    def __init__(self, causa: ErrorDispositivo, rutas: list[str]):
        super().__init__(causa.mensaje, detalle=getattr(causa, "detalle", ""),
                         sugerencia=getattr(causa, "sugerencia", ""))
        self.rutas = list(rutas)


def bits_de_origen(*, alimentador: bool, duplex: bool) -> int:
    """Los bits de DOCUMENT_HANDLING_SELECT para el trabajo pedido.

    Pura para poder probarla: pedir dúplex sin alimentador es un error de
    programación que, mandado al driver, se traduce en un com_error
    incomprensible o —peor— en que escanee sólo la primera cara sin decir
    nada.
    """
    if duplex and not alimentador:
        raise ValueError("El dúplex sólo existe con alimentador: son las "
                         "dos caras de la hoja que pasa por él.")
    if not alimentador:
        return WIA_SEL_FLATBED
    return WIA_SEL_FEEDER | (WIA_SEL_DUPLEX if duplex else 0)


def configurar_lote(dispositivo, *, alimentador: bool, duplex: bool,
                    paginas: int = WIA_TODAS_LAS_PAGINAS) -> None:
    """Deja el dispositivo listo para escanear del alimentador.

    Si el driver rechaza alguna propiedad se sigue igual: muchos aceptan
    sólo un subconjunto, y fallar acá impediría escanear en aparatos donde
    el trabajo habría salido bien con los valores por defecto.
    """
    seleccion = bits_de_origen(alimentador=alimentador, duplex=duplex)
    for propiedad, valor in ((WIA_DPS_DOCUMENT_HANDLING_SELECT, seleccion),
                             (WIA_DPS_PAGES, int(paginas))):
        try:
            dispositivo.Properties(str(propiedad)).Value = valor
        except Exception as e:                       # noqa: BLE001
            log.info("El escáner no aceptó la propiedad %s=%s: %s",
                     propiedad, valor, e)


def _fijar_dpi(item, dpi: int) -> None:
    for propiedad in (WIA_IPS_XRES, WIA_IPS_YRES):
        try:
            item.Properties(str(propiedad)).Value = int(dpi)
        except Exception:                            # noqa: BLE001
            log.debug("El escáner no admite fijar la propiedad %s", propiedad)


def adquirir_lote(destino_de, *, dpi: int = 300, alimentador: bool = True,
                  duplex: bool = False, id_dispositivo: str = "",
                  al_llegar=None, cancelado=None,
                  maximo: int = LOTE_MAX_PAGINAS) -> list[str]:
    """Escanea todo el taco del alimentador y devuelve las rutas guardadas.

    `destino_de(n)` da la ruta del archivo de la página n (0-based);
    `al_llegar(ruta, n)` se llama con cada página apenas está en disco, para
    que la pantalla la muestre sin esperar a que termine el lote; y
    `cancelado()` se consulta entre páginas.

    Cómo termina
    ------------
    El bucle no sabe de antemano cuántas hojas hay: le pide una tras otra
    hasta que el escáner contesta WIA_ERROR_PAPER_EMPTY, que es la forma
    NORMAL de terminar. Si eso pasa en la primera página, es que la bandeja
    estaba vacía, y ahí sí es un error que hay que contar.

    `maximo` es un tope de cordura: si un driver nunca avisa que se quedó
    sin papel —los hay— el bucle llenaría el disco.

    Debe correr en un hilo con COM inicializado (usar com_inicializado()).
    """
    com = _importar_com()
    if com is None:
        raise ErrorDispositivo(
            "No se pudieron cargar los componentes de Windows para escanear.",
            sugerencia="Instalalos con:  pip install pywin32")

    import os

    _, cliente = com
    manager = cliente.Dispatch("WIA.DeviceManager")
    dispositivo = _conectar(manager, id_dispositivo)
    configurar_lote(dispositivo, alimentador=alimentador, duplex=duplex)

    rutas: list[str] = []
    while len(rutas) < maximo:
        if cancelado is not None and cancelado():
            break
        try:
            item = dispositivo.Items(1)
            _fijar_dpi(item, dpi)
            imagen = item.Transfer(WIA_FORMATO_PNG)
        except Exception as e:                       # noqa: BLE001
            if es_fin_de_papel(e):
                if rutas:
                    break                            # se terminó el taco: ok
                raise ErrorDispositivo(
                    "No hay papel en el alimentador.",
                    detalle=str(e),
                    sugerencia="Cargá las hojas en la bandeja y volvé a "
                               "intentar.") from None
            if es_cancelacion_usuario(e):
                if rutas:
                    break                            # se queda con lo escaneado
                raise                                # crudo: lo reconoce el worker
            if rutas:
                # Un atasco a mitad del taco no debe tirar a la basura lo
                # que ya se escaneó: se corta acá y el llamador decide.
                raise ErrorLoteParcial(interpretar_error_wia(e), rutas) from e
            raise interpretar_error_wia(e) from e

        ruta = destino_de(len(rutas))
        imagen.SaveFile(ruta)
        if not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
            raise ErrorDispositivo(
                "El escáner devolvió una página vacía.",
                sugerencia="Revisá que el papel esté bien colocado.")
        rutas.append(ruta)
        if al_llegar is not None:
            al_llegar(ruta, len(rutas))

    if not rutas:
        raise ErrorDispositivo(
            "El escáner no devolvió ninguna página.",
            sugerencia="Revisá que el papel esté bien colocado y volvé a "
                       "intentar.")
    return rutas


def _conectar(manager, id_dispositivo: str = ""):
    """Conecta con el escáner pedido, o con el primero que haya."""
    infos = manager.DeviceInfos
    for i in range(1, infos.Count + 1):              # WIA indexa desde 1
        info = infos(i)
        if int(info.Type) != WIA_TIPO_ESCANER:
            continue
        if id_dispositivo and str(info.DeviceID) != id_dispositivo:
            continue
        return info.Connect()
    raise ErrorDispositivo(
        "No se detectó ningún escáner conectado.",
        sugerencia="Verificá que esté encendido y que Windows lo reconozca "
                   "en Configuración → Impresoras y escáneres.")


def interpretar_error_wia(error: Exception) -> ErrorDispositivo:
    """Traduce un com_error de WIA a algo que se pueda leer.

    Los códigos vienen del propio WIA; sin traducir, el usuario recibe
    un `com_error (-2147024891, ...)` que no le dice absolutamente nada.
    """
    texto = str(error)
    bajo = texto.lower()

    conocidos = (
        ("0x80210006", "El escáner está ocupado.",
         "Esperá a que termine el trabajo en curso o reinicialo."),
        ("0x80210015", "No se detectó ningún escáner.",
         "Verificá que esté encendido y conectado."),
        ("0x80210064", "El escaneo falló durante la captura.",
         "Revisá que el papel esté bien colocado y volvé a intentar."),
        ("0x8021000a", "El escáner no está listo.",
         "Esperá unos segundos a que termine de calentar y reintentá."),
        ("0x80070005", "Windows denegó el acceso al escáner.",
         "Puede estar en uso por otro programa. Cerralo y reintentá."),
        ("coinitialize", "Error interno al inicializar el escáner.",
         "Reiniciá la aplicación. Si persiste, reportalo."),
        # Los tres de abajo son propios del alimentador. Con cristal casi
        # no aparecen; con ADF son moneda corriente y merecen su mensaje.
        (WIA_ERROR_PAPER_JAM, "Se atascó el papel en el alimentador.",
         "Abrí la tapa, sacá la hoja trabada con cuidado y volvé a cargar "
         "el taco. Las páginas que ya se escanearon quedan en la lista."),
        (WIA_ERROR_PAPER_PROBLEM, "El alimentador no pudo tomar la hoja.",
         "Emparejá el taco, revisá que no haya ganchos ni hojas pegadas y "
         "cargalo de nuevo."),
        (WIA_ERROR_PAPER_EMPTY, "No hay papel en el alimentador.",
         "Cargá las hojas en la bandeja y volvé a intentar."),
        (WIA_ERROR_COVER_OPEN, "La tapa del escáner está abierta.",
         "Cerrala y reintentá."),
    )
    for codigo, mensaje, sugerencia in conocidos:
        if codigo in bajo:
            return ErrorDispositivo(mensaje, detalle=texto, sugerencia=sugerencia)

    return ErrorDispositivo(
        "El escáner reportó un error.",
        detalle=texto,
        sugerencia="Verificá que esté encendido y conectado. Si el problema "
                   "sigue, probá cargar la imagen desde el disco.")


def es_cancelacion_usuario(error: Exception) -> bool:
    """True si el 'error' es en realidad el usuario cerrando el diálogo.

    Ojo con lo que NO entra acá: 0x80210003 es WIA_ERROR_PAPER_EMPTY, "no
    hay papel", y durante mucho tiempo estuvo en esta lista. Con el
    cristal daba igual —ese código casi no aparece— pero con alimentador
    es la señal NORMAL de que se terminó el taco: tomarla por una
    cancelación haría que un lote de 20 hojas terminara en silencio como
    si el usuario hubiera cerrado el diálogo, y que escanear con la
    bandeja vacía no dijera nada. Va en `es_fin_de_papel()`.
    """
    texto = str(error).lower()
    return any(x in texto for x in ("cancel", "user cancel"))


def es_fin_de_papel(error: Exception) -> bool:
    """True si el escáner avisó que se quedó sin hojas.

    Es cómo termina un lote del alimentador cuando salió bien, y también
    lo que se recibe al pedirle que escanee con la bandeja vacía. Quien
    llama distingue los dos casos por si alcanzó a traer alguna página.
    """
    return WIA_ERROR_PAPER_EMPTY in str(error).lower()


def es_atasco(error: Exception) -> bool:
    """True si el papel se trabó. Distinto de quedarse sin papel: acá hay
    una hoja adentro del aparato y el usuario tiene que ir a sacarla."""
    texto = str(error).lower()
    return WIA_ERROR_PAPER_JAM in texto or "paper jam" in texto
