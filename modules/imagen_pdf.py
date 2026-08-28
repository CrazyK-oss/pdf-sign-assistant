"""
modules/imagen_pdf.py
============================================================
Conversión de una imagen a un PDF de una página.

Estaba dentro de fase_guardar.py, pero ahora lo usan dos herramientas
—firmar un PDF y escanear a PDF—, así que vive aparte. No importa Qt:
es puro Pillow/reportlab, y por eso se puede probar sin abrir ventana.

Tres motores, en orden
----------------------
1. **reportlab** — el principal: es el más robusto en Windows con
   JPG/PNG/BMP y respeta el DPI de la imagen, así que la página del PDF
   sale del tamaño físico correcto.
2. **img2pdf** — alternativa, y corre en un SUBPROCESO aislado: puede
   crashear a nivel de extensión C (pikepdf/libjpeg) y ahí ningún
   try/except de Python llega a atrapar nada. Se saltea en modo
   congelado: dentro de un .exe de PyInstaller `sys.executable` es la
   propia app, así que "convertir la imagen" abría una segunda instancia
   del programa.
3. **Pillow** — último recurso, siempre disponible.

Si uno falla se pasa al siguiente y se deja anotado en el log, en vez de
abortar el guardado entero por un motor que no le gustó un formato.

El tamaño del archivo
---------------------
Hasta la 0.11.1 la imagen se embebía **sin pérdida**: reportlab la metía
comprimida con Flate, que para un escaneo —papel con ruido, tinta, sombras—
es lo peor posible. Medido con una hoja A4 real:

    600 dpi sin pérdida    3,4 MB por página
    300 dpi JPEG q88       0,58 MB      ( 6x menos)
    200 dpi JPEG q80       0,12 MB      (36x menos)

Con tres hojas firmadas eso eran 10 MB, y Outlook rechaza los adjuntos que
pasan de 20. El documento no se podía mandar, que es justamente para lo que
la aplicación lo produce.

Ahora la imagen se remuestrea al DPI del preset y se embebe como JPEG.
reportlab lo pasa **tal cual** al PDF (filtro DCTDecode), sin recodificar,
así que no hay doble pérdida. `SIN_PERDIDA` conserva el comportamiento
viejo para quien lo necesite.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


# ─────────────────────────────────────────────────────────────────────────
#  Calidad de salida
# ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CalidadPDF:
    """Cuánto se remuestrea y se comprime cada página."""

    clave: str
    nombre: str
    descripcion: str
    #: Tope de resolución. Si el escaneo viene con más, se reduce.
    dpi_max: int
    #: Calidad JPEG (1-95). Con 0 se embebe sin pérdida.
    jpeg: int

    @property
    def sin_perdida(self) -> bool:
        return self.jpeg <= 0


#: Los números salen de comparar los recortes a ojo sobre un A4 escaneado:
#: a 200 dpi con q80 el texto y el trazo de la firma son indistinguibles
#: del original, y recién a 150/q70 se empieza a notar el texto más lavado.
ALTA = CalidadPDF(
    "alta", "Alta",
    "300 dpi. Para archivar o reimprimir; el archivo pesa unas 6 veces menos "
    "que sin comprimir.", 300, 88)

EQUILIBRADA = CalidadPDF(
    "equilibrada", "Equilibrada",
    "200 dpi. Indistinguible en pantalla y se imprime bien. Es la que "
    "conviene para mandar por correo.", 200, 80)

MINIMA = CalidadPDF(
    "minima", "Mínima",
    "150 dpi. Para documentos largos que igual no entran; el texto se ve un "
    "poco más lavado.", 150, 70)

SIN_PERDIDA = CalidadPDF(
    "sin_perdida", "Sin comprimir",
    "Guarda el escaneo tal cual, sin remuestrear ni comprimir. Es el "
    "comportamiento anterior: da archivos enormes.", 0, 0)

CALIDADES: dict[str, CalidadPDF] = {
    c.clave: c for c in (ALTA, EQUILIBRADA, MINIMA, SIN_PERDIDA)
}

#: Orden de peor a mejor compresión, para "probá con una más liviana".
ORDEN = ("sin_perdida", "alta", "equilibrada", "minima")

CALIDAD_DEFECTO = EQUILIBRADA


#: Tope de adjunto que aplican Outlook y Exchange por omisión. Muchas
#: organizaciones lo bajan todavía más, así que es configurable.
LIMITE_CORREO_MB = 20


def formatear_peso(bytes_: int) -> str:
    """'2,4 MB' — con coma decimal, que es lo que se usa en español."""
    if bytes_ < 1024:
        return f"{bytes_} B"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.0f} kB"
    return f"{bytes_ / (1024 * 1024):.1f} MB".replace(".", ",")


def excede_limite(bytes_: int, limite_mb: float = LIMITE_CORREO_MB) -> bool:
    """True si el archivo no va a entrar como adjunto."""
    return bytes_ > max(1.0, float(limite_mb)) * 1024 * 1024


def calidad(clave: str | CalidadPDF | None) -> CalidadPDF:
    """Resuelve una clave de calidad, con el default como red de seguridad."""
    if isinstance(clave, CalidadPDF):
        return clave
    return CALIDADES.get(str(clave or ""), CALIDAD_DEFECTO)


def opciones_calidad() -> list[tuple[str, str, str]]:
    """(clave, nombre, descripción) de cada calidad, para armar un selector."""
    return [(CALIDADES[k].clave, CALIDADES[k].nombre, CALIDADES[k].descripcion)
            for k in ORDEN[::-1]]      # de la más liviana a la más pesada


def siguiente_mas_liviana(actual: str | CalidadPDF | None) -> CalidadPDF | None:
    """La calidad que sigue si el archivo quedó demasiado grande."""
    clave = calidad(actual).clave
    try:
        i = ORDEN.index(clave)
    except ValueError:                               # pragma: no cover
        return CALIDAD_DEFECTO
    return calidad(ORDEN[i + 1]) if i + 1 < len(ORDEN) else None


# ─────────────────────────────────────────────────────────────────────────
#  Script auxiliar que corre img2pdf en subproceso aislado
# ─────────────────────────────────────────────────────────────────────────
_IMG2PDF_WORKER_SCRIPT = """
import sys, img2pdf
ruta_img = sys.argv[1]
ruta_out  = sys.argv[2]
with open(ruta_img, "rb") as f:
    datos = img2pdf.convert(f)
with open(ruta_out, "wb") as f:
    f.write(datos)
"""


# ─────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────

def _normalizar_modo_pillow(img):
    """Convierte la imagen al modo correcto para guardar como PDF con Pillow.

    Pillow soporta RGB y L en PDF. Cualquier otro modo se convierte:
      - RGBA / PA  → composición sobre fondo blanco → RGB
      - P (paleta) → RGB
      - L, LA      → L (escala de grises, alpha descartada)
      - CMYK y resto → RGB
    """
    modo = img.mode
    if modo in ("RGB", "L"):
        return img
    if modo in ("RGBA", "PA"):
        from PIL import Image as _Image
        fondo = _Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        fondo.paste(rgba, mask=rgba.split()[3])
        return fondo
    if modo == "LA":
        return img.convert("L")
    return img.convert("RGB")


def aplicar_rotacion(ruta_imagen: str, grados: int) -> tuple[str, bool]:
    """Devuelve (ruta, es_temporal) con la imagen ya rotada.

    Rota en sentido horario para coincidir con lo que muestra la vista
    previa (QTransform().rotate() gira en horario; PIL, en antihorario).
    El archivo original nunca se toca: se escribe una copia temporal.
    """
    grados = int(grados) % 360
    if grados == 0:
        return ruta_imagen, False

    from PIL import Image
    with Image.open(ruta_imagen) as img:
        rotada = img.rotate(-grados, expand=True)
        rotada = _normalizar_modo_pillow(rotada)
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        # Conserva el DPI para que la página resultante mida lo mismo
        dpi = img.info.get("dpi")
        if dpi:
            rotada.save(tmp.name, "PNG", dpi=dpi)
        else:
            rotada.save(tmp.name, "PNG")
    log.debug("Rotación %d° aplicada → %s", grados, tmp.name)
    return tmp.name, True


def borrar_si_existe(ruta: str | None) -> None:
    try:
        if ruta and Path(ruta).exists():
            os.remove(ruta)
    except OSError:
        pass


def _dpi_de(img, defecto: int = 150) -> float:
    """DPI horizontal de la imagen, saneado.

    Los escáneres a veces no lo declaran, o declaran 0 o 1. Cualquiera de
    esas haría que la página del PDF saliera del tamaño equivocado, o que
    la división para remuestrear explotara.
    """
    dpi = img.info.get("dpi", (defecto, defecto))
    if isinstance(dpi, (int, float)):
        dpi = (dpi, dpi)
    try:
        valor = float(dpi[0])
    except (TypeError, ValueError, IndexError):
        return float(defecto)
    return valor if 20 <= valor <= 2400 else float(defecto)


def preparar_para_pdf(ruta_imagen: str,
                      cal: CalidadPDF | None = None) -> tuple[str, bool]:
    """Remuestrea y comprime la imagen antes de embeberla.

    Devuelve (ruta, es_temporal). Con SIN_PERDIDA devuelve el original sin
    tocar, para conservar el comportamiento anterior.

    La clave del ahorro es guardar como JPEG: reportlab detecta el formato
    y lo copia al PDF con filtro DCTDecode, sin volver a codificar, así que
    la pérdida ocurre una sola vez y acá.
    """
    cal = calidad(cal)
    if cal.sin_perdida:
        return ruta_imagen, False

    try:
        # El import va DENTRO del try a propósito: sin Pillow, comprimir
        # es imposible pero guardar no, y el llamador debe recibir el
        # original en vez de una excepción.
        from PIL import Image

        with Image.open(ruta_imagen) as img:
            dpi = _dpi_de(img)
            trabajo = img

            if dpi > cal.dpi_max:
                factor = cal.dpi_max / dpi
                ancho = max(1, round(img.width * factor))
                alto = max(1, round(img.height * factor))
                trabajo = img.resize((ancho, alto), Image.LANCZOS)
                # El DPI se recalcula desde los píxeles que quedaron, no se
                # asume dpi_max: así el tamaño físico (px/dpi) se mantiene
                # lo más cerca posible del original. No puede quedar exacto
                # porque JFIF guarda la densidad como entero, pero el error
                # es menor a 1 punto (0,35 mm) en un A4. En el flujo de
                # firma ni eso importa: la página hereda el mediabox del
                # documento original.
                dpi = max(1, round(ancho * dpi / img.width))

            # JPEG no admite alpha ni paleta; la composición sobre blanco
            # la hace _normalizar_modo_pillow, que ya contempla los modos
            # raros que devuelven algunos drivers.
            trabajo = _normalizar_modo_pillow(trabajo)
            if trabajo.mode != "RGB":
                trabajo = trabajo.convert("RGB")

            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.close()
            trabajo.save(tmp.name, "JPEG", quality=cal.jpeg, optimize=True,
                         dpi=(dpi, dpi), subsampling=2)
    except Exception as e:                           # noqa: BLE001
        # Comprimir es una mejora, no un requisito: si falla, se sigue con
        # el original y el usuario obtiene un archivo grande pero correcto.
        log.warning("No se pudo comprimir %s (%s: %s); se usa el original",
                    ruta_imagen, type(e).__name__, e)
        return ruta_imagen, False

    log.debug("Comprimida a %s dpi q%d: %s → %s bytes",
              cal.dpi_max, cal.jpeg, ruta_imagen,
              Path(tmp.name).stat().st_size)
    return tmp.name, True


# ─────────────────────────────────────────────────────────────────────────
#  Motores
# ─────────────────────────────────────────────────────────────────────────

def _imagen_a_pdf_reportlab(ruta_imagen: str) -> str:
    """Convierte imagen a PDF de una página con reportlab (motor principal:
    es el más robusto en Windows con JPG/PNG/BMP)."""
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    with Image.open(ruta_imagen) as img:
        ancho_px, alto_px = img.size
        dpi_x = _dpi_de(img)
        dpi = img.info.get("dpi", (dpi_x, dpi_x))
        if isinstance(dpi, (int, float)):
            dpi = (dpi, dpi)
        dpi_y = dpi[1] if len(dpi) > 1 and 20 <= dpi[1] <= 2400 else dpi_x

    ancho_pt = ancho_px * 72.0 / dpi_x
    alto_pt = alto_px * 72.0 / dpi_y

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()

    c = canvas.Canvas(tmp.name, pagesize=(ancho_pt, alto_pt))
    c.drawImage(ImageReader(ruta_imagen), 0, 0,
                width=ancho_pt, height=alto_pt, preserveAspectRatio=False)
    c.save()

    if Path(tmp.name).stat().st_size == 0:
        borrar_si_existe(tmp.name)
        raise RuntimeError("reportlab generó un PDF vacío (0 bytes)")
    return tmp.name


def _imagen_a_pdf_pillow(ruta_imagen: str) -> str:
    """Convierte una imagen a PDF de una página usando Pillow."""
    from PIL import Image
    with Image.open(ruta_imagen) as img_orig:
        img = _normalizar_modo_pillow(img_orig)
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.close()
        img.save(tmp.name, "PDF", resolution=150)
    return tmp.name


def _imagen_a_pdf_img2pdf(ruta_imagen: str) -> str:
    """Convierte con img2pdf en un subproceso aislado.

    En modo congelado (PyInstaller) se salta: sys.executable apunta al
    propio .exe y lanzar `-c` abriría otra instancia de la aplicación.
    """
    if getattr(sys, "frozen", False):
        raise RuntimeError("img2pdf no se usa en modo congelado (.exe)")

    try:
        import importlib
        importlib.import_module("img2pdf")
    except ImportError as exc:
        raise ImportError("img2pdf no está instalado") from exc

    tmp_out = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_out.close()

    try:
        resultado = subprocess.run(
            [sys.executable, "-c", _IMG2PDF_WORKER_SCRIPT,
             ruta_imagen, tmp_out.name],
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        borrar_si_existe(tmp_out.name)
        raise RuntimeError("img2pdf: timeout tras 60 s") from exc
    except Exception as exc:
        borrar_si_existe(tmp_out.name)
        raise RuntimeError(f"img2pdf: error al lanzar subproceso — {exc}") from exc

    if resultado.returncode != 0:
        stderr = resultado.stderr.decode(errors="replace").strip()
        borrar_si_existe(tmp_out.name)
        raise RuntimeError(
            f"img2pdf terminó con código {resultado.returncode}. stderr: {stderr}")

    if Path(tmp_out.name).stat().st_size == 0:
        borrar_si_existe(tmp_out.name)
        raise RuntimeError("img2pdf generó un PDF vacío (0 bytes)")
    return tmp_out.name


# ─────────────────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────────────────

def convertir_imagen_a_pdf(ruta_imagen: str, rotacion: int = 0,
                           cal: CalidadPDF | str | None = None) -> str:
    """Convierte una imagen (con su rotación) a un PDF de una página.

    Devuelve la ruta de un archivo TEMPORAL: el llamador es responsable
    de borrarlo con borrar_si_existe() cuando termine de usarlo.

    Intenta reportlab → img2pdf (subproceso) → Pillow, en ese orden.
    """
    ruta_rotada, temp_rot = aplicar_rotacion(ruta_imagen, rotacion)
    ruta_lista, temp_jpg = preparar_para_pdf(ruta_rotada, cal)
    try:
        for nombre, motor in (
            ("reportlab", _imagen_a_pdf_reportlab),
            ("img2pdf", _imagen_a_pdf_img2pdf),
        ):
            try:
                ruta = motor(ruta_lista)
                log.debug("Conversión con %s OK → %s", nombre, ruta)
                return ruta
            except ImportError:
                log.debug("%s no disponible, probando el siguiente motor", nombre)
            except Exception as e:                   # noqa: BLE001
                log.warning("%s falló (%s: %s) — probando el siguiente motor",
                            nombre, type(e).__name__, e)

        log.debug("Usando Pillow como último fallback")
        return _imagen_a_pdf_pillow(ruta_lista)
    finally:
        if temp_jpg:
            borrar_si_existe(ruta_lista)
        if temp_rot:
            borrar_si_existe(ruta_rotada)


# Nombres antiguos, para no romper lo que ya los importaba.
_convertir_imagen_a_pdf = convertir_imagen_a_pdf
_borrar_si_existe = borrar_si_existe
