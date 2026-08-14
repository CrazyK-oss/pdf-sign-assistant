"""
tests/test_setup.py
============================================================
Tests de rutas y migración (modules/setup.py).

Cubren el cambio que permite instalar la app en Program Files: la
config, los logs y los documentos ya no se escriben junto al .exe.
La migración es lo más delicado — si se equivoca, un usuario pierde
sus documentos firmados — así que se testea a fondo.
"""

import json

import pytest

from modules import setup

# ── Configuración ─────────────────────────────────────────────────────────────

def test_cargar_config_inexistente_devuelve_defaults(tmp_path):
    config = setup.cargar_config(tmp_path / "no_existe.json")
    assert config["tema"] == "light"
    assert config["smtp_port"] == 587


def test_cargar_config_corrupta_no_rompe(tmp_path):
    ruta = tmp_path / "config.json"
    ruta.write_text("{esto no es json", encoding="utf-8")
    assert setup.cargar_config(ruta)["tema"] == "light"


def test_cargar_config_fusiona_con_defaults(tmp_path):
    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps({"email_user": "a@b.com"}), encoding="utf-8")
    config = setup.cargar_config(ruta)
    assert config["email_user"] == "a@b.com"
    assert config["smtp_server"] == "smtp.gmail.com"    # completado por defecto


def test_guardar_config_es_atomico(tmp_path):
    ruta = tmp_path / "config.json"
    setup.guardar_config({"email_user": "x@y.com", "tema": "dark"}, ruta)
    assert setup.cargar_config(ruta)["tema"] == "dark"
    # el temporal no debe quedar tirado
    assert not list(tmp_path.glob("*.tmp"))


def test_guardar_config_crea_el_directorio(tmp_path):
    ruta = tmp_path / "sub" / "carpeta" / "config.json"
    setup.guardar_config({"tema": "dark"}, ruta)
    assert ruta.is_file()


# ── Rutas ─────────────────────────────────────────────────────────────────────

def test_directorio_datos_no_escribe_junto_al_exe(monkeypatch):
    """La razón de ser del cambio: Program Files es de sólo lectura."""
    monkeypatch.setattr(setup, "es_portable", lambda: False)
    assert setup.directorio_datos() != setup.get_base_dir()


def test_modo_portable_deja_todo_junto_a_la_app(monkeypatch):
    monkeypatch.setattr(setup, "es_portable", lambda: True)
    assert setup.directorio_datos() == setup.get_base_dir()
    assert setup.directorio_documentos() == setup.get_base_dir() / "pdfs_firmados"


def test_directorio_datos_lleva_el_nombre_de_la_app(monkeypatch):
    monkeypatch.setattr(setup, "es_portable", lambda: False)
    assert setup.directorio_datos().name == setup.APP_NOMBRE


# ── Migración ─────────────────────────────────────────────────────────────────

def test_migracion_mueve_carpeta_completa(tmp_path):
    viejo = tmp_path / "viejo" / "pdfs_firmados"
    viejo.mkdir(parents=True)
    (viejo / "contrato.pdf").write_bytes(b"%PDF-1.4 contrato")
    nuevo = tmp_path / "nuevo" / "pdfs_firmados"

    movidos = setup.migrar_datos_antiguos([(viejo, nuevo)])

    assert movidos
    assert (nuevo / "contrato.pdf").read_bytes() == b"%PDF-1.4 contrato"
    assert not viejo.exists()


def test_migracion_mueve_archivo_suelto(tmp_path):
    viejo = tmp_path / "viejo" / "config.json"
    viejo.parent.mkdir(parents=True)
    viejo.write_text('{"tema": "dark"}', encoding="utf-8")
    nuevo = tmp_path / "nuevo" / "config.json"

    setup.migrar_datos_antiguos([(viejo, nuevo)])

    assert json.loads(nuevo.read_text(encoding="utf-8"))["tema"] == "dark"
    assert not viejo.exists()


def test_migracion_nunca_pisa_datos_nuevos(tmp_path):
    """Si el archivo ya existe del lado nuevo, gana el nuevo."""
    viejo = tmp_path / "viejo" / "pdfs_firmados"
    viejo.mkdir(parents=True)
    (viejo / "doc.pdf").write_bytes(b"VIEJO")

    nuevo = tmp_path / "nuevo" / "pdfs_firmados"
    nuevo.mkdir(parents=True)
    (nuevo / "doc.pdf").write_bytes(b"NUEVO")

    setup.migrar_datos_antiguos([(viejo, nuevo)])

    assert (nuevo / "doc.pdf").read_bytes() == b"NUEVO"
    assert (viejo / "doc.pdf").read_bytes() == b"VIEJO"   # el viejo sigue ahí


def test_migracion_fusiona_carpetas(tmp_path):
    """Destino existente: se suman los archivos que faltan del otro lado."""
    viejo = tmp_path / "viejo" / "pdfs_firmados"
    viejo.mkdir(parents=True)
    (viejo / "a.pdf").write_bytes(b"A")
    (viejo / "b.pdf").write_bytes(b"B")

    nuevo = tmp_path / "nuevo" / "pdfs_firmados"
    nuevo.mkdir(parents=True)
    (nuevo / "b.pdf").write_bytes(b"B-NUEVO")

    setup.migrar_datos_antiguos([(viejo, nuevo)])

    assert (nuevo / "a.pdf").read_bytes() == b"A"          # migrado
    assert (nuevo / "b.pdf").read_bytes() == b"B-NUEVO"    # respetado
    assert not (viejo / "a.pdf").exists()


def test_migracion_sin_datos_viejos_no_hace_nada(tmp_path):
    movidos = setup.migrar_datos_antiguos(
        [(tmp_path / "no_existe", tmp_path / "destino")])
    assert movidos == []
    assert not (tmp_path / "destino").exists()


def test_migracion_con_mismo_origen_y_destino(tmp_path):
    """En modo portable origen y destino coinciden: no debe autodestruirse."""
    ruta = tmp_path / "pdfs_firmados"
    ruta.mkdir()
    (ruta / "doc.pdf").write_bytes(b"DATOS")

    setup.migrar_datos_antiguos([(ruta, ruta)])

    assert (ruta / "doc.pdf").read_bytes() == b"DATOS"


def test_migracion_tolera_errores(tmp_path, monkeypatch):
    """Un fallo al mover no puede impedir que la app arranque."""
    viejo = tmp_path / "viejo"
    viejo.mkdir()
    (viejo / "x.pdf").write_bytes(b"X")

    def explota(*_a, **_k):
        raise OSError("disco lleno")

    monkeypatch.setattr(setup.shutil, "move", explota)
    assert setup.migrar_datos_antiguos([(viejo, tmp_path / "nuevo")]) == []


# ── Limpieza de huérfanos ─────────────────────────────────────────────────────

def test_limpiar_trabajos_huerfanos(tmp_path, monkeypatch):
    import os
    import time

    monkeypatch.setattr(setup, "CARPETA_TRABAJO", tmp_path)
    viejo = tmp_path / "viejo.pdf"
    reciente = tmp_path / "reciente.pdf"
    viejo.write_bytes(b"x")
    reciente.write_bytes(b"y")

    hace_diez_dias = time.time() - 10 * 86400
    os.utime(viejo, (hace_diez_dias, hace_diez_dias))

    assert setup.limpiar_trabajos_huerfanos(dias=7) == 1
    assert not viejo.exists()
    assert reciente.exists()


# ── Versión ───────────────────────────────────────────────────────────────────

def test_version_bien_formada():
    from modules.version import __version__, version_tupla

    partes = __version__.split(".")
    assert len(partes) == 3 and all(p.isdigit() for p in partes)

    tupla = version_tupla()
    assert len(tupla) == 4 and all(isinstance(n, int) for n in tupla)


@pytest.mark.parametrize("archivo", [
    "installer/pdf_sign_assistant.iss",
    ".github/workflows/release.yml",
])
def test_archivos_de_release_presentes(archivo):
    """Si alguien borra el instalador o el workflow, el release se rompe
    en silencio hasta que se intenta publicar."""
    from pathlib import Path
    assert (Path(__file__).parent.parent / archivo).is_file()
