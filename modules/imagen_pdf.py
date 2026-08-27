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
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


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
        dpi = img.info.get("dpi", (150, 150))
        if isinstance(dpi, (int, float)):
            dpi = (dpi, dpi)
        dpi_x = dpi[0] if dpi[0] > 0 else 150
        dpi_y = dpi[1] if dpi[1] > 0 else 150

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

def convertir_imagen_a_pdf(ruta_imagen: str, rotacion: int = 0) -> str:
    """Convierte una imagen (con su rotación) a un PDF de una página.

    Devuelve la ruta de un archivo TEMPORAL: el llamador es responsable
    de borrarlo con borrar_si_existe() cuando termine de usarlo.

    Intenta reportlab → img2pdf (subproceso) → Pillow, en ese orden.
    """
    ruta_rotada, temporal = aplicar_rotacion(ruta_imagen, rotacion)
    try:
        for nombre, motor in (
            ("reportlab", _imagen_a_pdf_reportlab),
            ("img2pdf", _imagen_a_pdf_img2pdf),
        ):
            try:
                ruta = motor(ruta_rotada)
                log.debug("Conversión con %s OK → %s", nombre, ruta)
                return ruta
            except ImportError:
                log.debug("%s no disponible, probando el siguiente motor", nombre)
            except Exception as e:                   # noqa: BLE001
                log.warning("%s falló (%s: %s) — probando el siguiente motor",
                            nombre, type(e).__name__, e)

        log.debug("Usando Pillow como último fallback")
        return _imagen_a_pdf_pillow(ruta_rotada)
    finally:
        if temporal:
            borrar_si_existe(ruta_rotada)


# Nombres antiguos, para no romper lo que ya los importaba.
_convertir_imagen_a_pdf = convertir_imagen_a_pdf
_borrar_si_existe = borrar_si_existe
