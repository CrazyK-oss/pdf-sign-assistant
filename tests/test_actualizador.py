"""
tests/test_actualizador.py
============================================================
Tests del actualizador interno (modules/actualizaciones.py).

Apuntan al módulo SIN Qt a propósito: el CI no instala PyQt6, y estos
tests verifican lógica, no interfaz.

Se testea la lógica pura: comparación de versiones, política de cuándo
comprobar, y el parseo de la respuesta del servidor (con datos falsos,
sin salir a internet). Un error acá se manifiesta como "nunca avisa de
las actualizaciones" o, peor, "ofrece bajar una versión anterior".
"""

import json
from datetime import datetime, timedelta

import pytest

from modules import actualizaciones as act

# ── Parseo de versiones ───────────────────────────────────────────────────────

@pytest.mark.parametrize("texto,esperado", [
    ("1.2.3",       (1, 2, 3, "")),
    ("v1.2.3",      (1, 2, 3, "")),
    ("  v0.8.0  ",  (0, 8, 0, "")),
    ("1.2.3-beta1", (1, 2, 3, "beta1")),
    ("10.20.30",    (10, 20, 30, "")),
])
def test_parsear_version_valida(texto, esperado):
    assert act.parsear_version(texto) == esperado


@pytest.mark.parametrize("texto", ["", "abc", "1.2", "v", "latest", None, "1.2.x"])
def test_parsear_version_invalida(texto):
    assert act.parsear_version(texto) is None


# ── Comparación ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b,esperado", [
    ("1.0.0", "1.0.1",  -1),
    ("1.0.1", "1.0.0",   1),
    ("1.0.0", "1.0.0",   0),
    ("1.9.0", "1.10.0", -1),      # comparación numérica, no alfabética
    ("0.9.9", "1.0.0",  -1),
    ("2.0.0", "1.9.9",   1),
    ("v1.0.0", "1.0.0",  0),      # la 'v' no cambia nada
])
def test_comparar_versiones(a, b, esperado):
    assert act.comparar_versiones(a, b) == esperado


def test_una_beta_es_anterior_a_la_final():
    assert act.comparar_versiones("1.2.3-beta1", "1.2.3") == -1
    assert act.comparar_versiones("1.2.3", "1.2.3-beta1") == 1


def test_version_invalida_no_dispara_actualizacion():
    """Ante una respuesta rara del servidor, no ofrecer nada."""
    assert act.comparar_versiones("1.0.0", "no-es-version") == 0
    assert not act.hay_version_nueva("1.0.0", "latest")


@pytest.mark.parametrize("actual,candidata,esperado", [
    ("0.8.0", "0.9.0", True),
    ("0.8.0", "0.8.0", False),
    ("0.9.0", "0.8.0", False),      # nunca "actualizar" hacia atrás
    ("1.0.0", "1.0.1", True),
])
def test_hay_version_nueva(actual, candidata, esperado):
    assert act.hay_version_nueva(actual, candidata) is esperado


# ── Política de comprobación ──────────────────────────────────────────────────

def test_no_comprueba_si_esta_desactivado():
    assert not act.toca_comprobar({"actualizaciones_automaticas": False})


def test_comprueba_la_primera_vez():
    assert act.toca_comprobar({})


def test_no_comprueba_dos_veces_el_mismo_dia():
    hace_una_hora = (datetime.now() - timedelta(hours=1)).isoformat()
    assert not act.toca_comprobar({"ultima_comprobacion": hace_una_hora})


def test_comprueba_pasadas_24_horas():
    ayer = (datetime.now() - timedelta(hours=25)).isoformat()
    assert act.toca_comprobar({"ultima_comprobacion": ayer})


def test_fecha_corrupta_no_rompe():
    assert act.toca_comprobar({"ultima_comprobacion": "no es una fecha"})


def test_marcar_comprobacion_deja_fecha_legible():
    config = {}
    act.marcar_comprobacion(config)
    datetime.fromisoformat(config["ultima_comprobacion"])   # no debe lanzar
    assert not act.toca_comprobar(config)                   # y frena la próxima


def test_version_ignorada():
    config = {"version_ignorada": "0.9.0"}
    assert act.esta_ignorada(config, "0.9.0")
    assert not act.esta_ignorada(config, "1.0.0")           # la siguiente sí avisa
    assert not act.esta_ignorada({}, "0.9.0")


# ── Lectura de la respuesta del servidor ──────────────────────────────────────

def _respuesta_falsa(monkeypatch, payload: dict):
    """Sustituye la llamada de red por una respuesta fija."""
    class RespuestaFalsa:
        def read(self):
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(act, "_abrir", lambda *a, **k: RespuestaFalsa())


RELEASE_OK = {
    "tag_name": "v0.9.0",
    "body": "Arregla la impresión",
    "html_url": "https://github.com/x/y/releases/tag/v0.9.0",
    "assets": [
        {"name": "PDFSignAssistant-0.9.0-Setup.exe",
         "browser_download_url": "https://ejemplo/Setup.exe", "size": 42_000_000},
        {"name": "SHA256SUMS.txt",
         "browser_download_url": "https://ejemplo/SHA256SUMS.txt", "size": 200},
        {"name": "PDFSignAssistant-0.9.0-portable.zip",
         "browser_download_url": "https://ejemplo/portable.zip", "size": 44_000_000},
    ],
}


def test_consultar_encuentra_instalador_y_hashes(monkeypatch):
    _respuesta_falsa(monkeypatch, RELEASE_OK)
    info = act.consultar_ultima_version()

    assert info is not None
    assert info.version == "0.9.0"                  # sin la 'v'
    assert info.notas == "Arregla la impresión"
    assert info.url_instalador == "https://ejemplo/Setup.exe"
    assert info.nombre_instalador == "PDFSignAssistant-0.9.0-Setup.exe"
    assert info.url_sumas == "https://ejemplo/SHA256SUMS.txt"
    assert info.tamano == 42_000_000


def test_consultar_ignora_release_sin_version_valida(monkeypatch):
    _respuesta_falsa(monkeypatch, {"tag_name": "ultima", "assets": []})
    assert act.consultar_ultima_version() is None


def test_consultar_sin_instalador_no_es_instalable(monkeypatch):
    _respuesta_falsa(monkeypatch, {
        "tag_name": "v1.0.0", "body": "", "html_url": "https://x", "assets": [],
    })
    info = act.consultar_ultima_version()
    assert info is not None
    assert not info.instalable          # sin Setup.exe no hay nada que instalar


def test_consultar_sin_red_devuelve_none(monkeypatch):
    def explota(*_a, **_k):
        raise OSError("network unreachable")

    monkeypatch.setattr(act, "_abrir", explota)
    assert act.consultar_ultima_version() is None       # no debe propagar


def test_modo_portable_no_ofrece_instalar(monkeypatch):
    _respuesta_falsa(monkeypatch, RELEASE_OK)
    monkeypatch.setattr(act, "es_portable", lambda: True)
    info = act.consultar_ultima_version()
    assert info.url_instalador          # el asset existe…
    assert not info.instalable          # …pero no se instala sobre un portable


# ── Verificación de integridad ────────────────────────────────────────────────

def test_sha256_esperado_encuentra_la_linea(monkeypatch):
    contenido = (
        "aaaa1111  PDFSignAssistant-0.9.0-portable.zip\n"
        "bbbb2222  PDFSignAssistant-0.9.0-Setup.exe\n"
    )

    class R:
        def read(self):
            return contenido.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(act, "_abrir", lambda *a, **k: R())
    assert act.sha256_esperado("u", "PDFSignAssistant-0.9.0-Setup.exe") == "bbbb2222"
    assert act.sha256_esperado("u", "no-existe.exe") is None


# ── Descarga verificada ───────────────────────────────────────────────────────
#  Es el punto más delicado del actualizador: acá se decide si se ejecuta
#  un binario bajado de internet. Antes vivía dentro de un QThread y no
#  se podía probar.

import hashlib


def _simular_descarga(monkeypatch, contenido: bytes, sumas: str | None):
    """Simula el servidor: devuelve `contenido` y, si se pide, SHA256SUMS."""
    class Respuesta:
        def __init__(self, datos, headers=None):
            self._datos = datos
            self._pos = 0
            self.headers = headers or {"Content-Length": str(len(datos))}

        def read(self, n=-1):
            if n is None or n < 0:
                trozo, self._pos = self._datos[self._pos:], len(self._datos)
                return trozo
            trozo = self._datos[self._pos:self._pos + n]
            self._pos += len(trozo)
            return trozo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def abrir(url, binario=False):
        if "SHA256SUMS" in url:
            if sumas is None:
                raise OSError("no hay sumas")
            return Respuesta(sumas.encode())
        return Respuesta(contenido)

    monkeypatch.setattr(act, "_abrir", abrir)


def _info(nombre="Setup.exe", con_sumas=True):
    return act.InfoActualizacion(
        version="9.9.9", notas="", url_pagina="https://x",
        url_instalador="https://ejemplo/Setup.exe", nombre_instalador=nombre,
        url_sumas="https://ejemplo/SHA256SUMS.txt" if con_sumas else "",
        tamano=len(b"instalador-falso"))


def test_descarga_con_hash_correcto(tmp_path, monkeypatch):
    contenido = b"instalador-falso"
    digest = hashlib.sha256(contenido).hexdigest()
    _simular_descarga(monkeypatch, contenido, f"{digest}  Setup.exe\n")

    pasos = []
    ruta = act.descargar_verificado(_info(), carpeta=tmp_path,
                                    progreso=lambda p, t: pasos.append(p))

    from pathlib import Path
    assert Path(ruta).read_bytes() == contenido
    assert pasos and pasos[-1] == 100


def test_descarga_con_hash_alterado_se_rechaza(tmp_path, monkeypatch):
    """Lo que impide ejecutar un binario manipulado o corrupto."""
    _simular_descarga(monkeypatch, b"binario-MANIPULADO",
                      f"{'0' * 64}  Setup.exe\n")

    with pytest.raises(ValueError) as info:
        act.descargar_verificado(_info(), carpeta=tmp_path)

    assert "no coincide" in str(info.value)
    # Y no puede quedar el archivo tirado listo para ejecutarse
    assert list(tmp_path.iterdir()) == []


def test_descarga_sin_sumas_publicadas_igual_funciona(tmp_path, monkeypatch):
    """Un Release viejo puede no tener SHA256SUMS: se avisa, no se bloquea."""
    _simular_descarga(monkeypatch, b"instalador", None)
    ruta = act.descargar_verificado(_info(con_sumas=False), carpeta=tmp_path)
    from pathlib import Path
    assert Path(ruta).exists()


def test_descarga_cancelada_no_deja_archivo(tmp_path, monkeypatch):
    _simular_descarga(monkeypatch, b"x" * 200_000, None)

    with pytest.raises(InterruptedError):
        act.descargar_verificado(_info(con_sumas=False), carpeta=tmp_path,
                                 cancelado=lambda: True)
    assert list(tmp_path.iterdir()) == []


def test_descarga_rechaza_archivo_gigante(tmp_path, monkeypatch):
    _simular_descarga(monkeypatch, b"x" * 10, None)
    monkeypatch.setattr(act, "TAM_MAXIMO", 5)

    with pytest.raises(ValueError):
        act.descargar_verificado(_info(con_sumas=False), carpeta=tmp_path)
    assert list(tmp_path.iterdir()) == []
