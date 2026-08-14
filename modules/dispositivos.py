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
    """True si el 'error' es en realidad el usuario cerrando el diálogo."""
    texto = str(error).lower()
    return any(x in texto for x in ("cancel", "0x80210003", "user cancel"))
