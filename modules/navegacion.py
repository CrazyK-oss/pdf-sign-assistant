"""
modules/navegacion.py
============================================================
El menú de herramientas: la barra lateral y la pantalla de inicio.

La aplicación dejó de ser "una pantalla que firma PDFs" para ser un
conjunto de herramientas que trabajan con PDFs. Este módulo es el
esqueleto de esa idea:

  CATALOGO          qué herramientas existen (datos, sin Qt)
  BarraLateral      navegación permanente a la izquierda
  PantallaInicio    el launcher, con una tarjeta por herramienta

Agregar una herramienta nueva es sumar una entrada a CATALOGO y
registrar su widget en la ventana principal. Ni la barra lateral ni el
inicio hay que tocarlos: los dos se construyen a partir del catálogo.

La barra lateral se colapsa a una tira de iconos cuando la ventana se
angosta, en vez de comerse la mitad del ancho útil o desaparecer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from modules.theme import BREAKPOINT, SIZE, SPACE, is_dark, repolish
from modules.ui import (
    AreaScroll,
    Chip,
    TarjetaHerramienta,
    boton,
    etiqueta,
    icono_label,
    separador,
)

# ═══════════════════════════════════════════════════════════════════════════════
#  Catálogo de herramientas — datos puros
# ═══════════════════════════════════════════════════════════════════════════════

INICIO = "inicio"


@dataclass(frozen=True)
class Herramienta:
    """Una entrada del menú.

    `id` es la clave con la que la ventana principal identifica su
    página en el QStackedWidget; el resto es cómo se presenta.
    """

    id: str
    titulo: str
    #: Etiqueta corta para la barra lateral, donde no entra el título largo.
    titulo_corto: str
    descripcion: str
    icono: str
    chip: str = ""
    tono_chip: str = "primary"
    atajo: str = ""
    disponible: bool = True


CATALOGO: tuple[Herramienta, ...] = (
    Herramienta(
        id="firmar",
        titulo="Firmar un PDF",
        titulo_corto="Firmar un PDF",
        descripcion=(
            "Imprimí las páginas que necesitás firmar, firmalas a mano, "
            "escaneálas y la app las reemplaza dentro del documento original."
        ),
        icono="firma",
        chip="El flujo completo",
        tono_chip="primary",
        atajo="Ctrl+1",
    ),
    Herramienta(
        id="escanear",
        titulo="Escanear a PDF",
        titulo_corto="Escanear a PDF",
        descripcion=(
            "Armá un PDF nuevo desde el escáner, página por página. "
            "Reordenalas, giralas y guardá el documento terminado."
        ),
        icono="escaner",
        atajo="Ctrl+2",
    ),
    Herramienta(
        id="unir",
        titulo="Unir y dividir PDFs",
        titulo_corto="Unir y dividir",
        descripcion=(
            "Pegá varios PDF en uno solo, o separá uno en varios archivos. "
            "El texto se conserva: las páginas se copian, no se convierten "
            "en imagen."
        ),
        icono="unir",
        chip="Nuevo",
        tono_chip="ok",
        atajo="Ctrl+3",
    ),
)


def buscar(id_herramienta: str) -> Herramienta | None:
    for h in CATALOGO:
        if h.id == id_herramienta:
            return h
    return None


def ids() -> tuple[str, ...]:
    return tuple(h.id for h in CATALOGO)


# ═══════════════════════════════════════════════════════════════════════════════
#  Barra lateral
# ═══════════════════════════════════════════════════════════════════════════════

class BarraLateral(QWidget):
    """Navegación permanente: marca arriba, herramientas al medio,
    acciones globales abajo.

    Señales:
      herramienta_elegida(str)  id del catálogo, o INICIO
      accion(str)               'ajustes' | 'carpeta' | 'tema'
    """

    herramienta_elegida = pyqtSignal(str)
    accion = pyqtSignal(str)

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.setObjectName("barraLateral")
        self.setFixedWidth(SIZE["sidebar"])
        self._compacta = False
        self._botones: dict[str, QWidget] = {}
        self._textos: dict[QWidget, str] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE["md"], SPACE["lg"], SPACE["md"], SPACE["md"])
        lay.setSpacing(SPACE["xs"])

        lay.addWidget(self._marca(version))
        lay.addSpacing(SPACE["md"])

        self.lbl_seccion = etiqueta("HERRAMIENTAS", rol="seccion")
        lay.addWidget(self.lbl_seccion)
        lay.addSpacing(SPACE["xs"])

        lay.addWidget(self._nav(INICIO, "Inicio", "cuadricula",
                                "Ver todas las herramientas (Ctrl+0)"))
        for herramienta in CATALOGO:
            pista = herramienta.descripcion
            if herramienta.atajo:
                pista = f"{pista}\n\n{herramienta.atajo}"
            lay.addWidget(self._nav(herramienta.id, herramienta.titulo_corto,
                                    herramienta.icono, pista))

        lay.addStretch(1)
        lay.addWidget(separador())
        lay.addSpacing(SPACE["xs"])

        self.btn_carpeta = self._accion("carpeta", "Documentos", "carpeta",
                                        "Abrir la carpeta de documentos firmados")
        self.btn_ajustes = self._accion("ajustes", "Ajustes", "engranaje",
                                        "Preferencias de la aplicación")
        self.btn_tema = self._accion("tema", "", "sol", "")
        for b in (self.btn_carpeta, self.btn_ajustes, self.btn_tema):
            lay.addWidget(b)
        self.sincronizar_tema()

    # -- construcción --------------------------------------------------------
    def _marca(self, version: str) -> QWidget:
        marco = QFrame()
        marco.setObjectName("marca")
        lay = QHBoxLayout(marco)
        lay.setContentsMargins(SPACE["sm"], 0, 0, 0)
        lay.setSpacing(SPACE["sm"] + 2)

        self.icono_marca = icono_label("firma", SIZE["icono_md"], color="primary")
        lay.addWidget(self.icono_marca)

        col = QVBoxLayout()
        col.setSpacing(0)
        self.lbl_marca = etiqueta("PDF Sign Assistant")
        self.lbl_marca.setObjectName("marcaTitulo")
        self.lbl_version = etiqueta(f"v{version}")
        self.lbl_version.setObjectName("marcaVersion")
        col.addWidget(self.lbl_marca)
        col.addWidget(self.lbl_version)
        lay.addLayout(col, 1)
        return marco

    def _nav(self, id_destino: str, texto: str, icono: str, pista: str) -> QWidget:
        b = boton(f"  {texto}", variant="nav", icono=icono, tooltip=pista,
                  checkable=True, height=SIZE["nav"],
                  on_click=lambda: self.herramienta_elegida.emit(id_destino))
        b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._botones[id_destino] = b
        self._textos[b] = f"  {texto}"
        return b

    def _accion(self, clave: str, texto: str, icono: str, pista: str) -> QWidget:
        b = boton(f"  {texto}" if texto else "", variant="nav", icono=icono,
                  tooltip=pista, height=SIZE["nav"],
                  on_click=lambda: self.accion.emit(clave))
        b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._textos[b] = f"  {texto}" if texto else ""
        return b

    # -- estado --------------------------------------------------------------
    def set_activa(self, id_destino: str) -> None:
        """Marca cuál está abierta. Los botones no son un grupo exclusivo de
        Qt porque también se navega por atajo y por las tarjetas del inicio."""
        for clave, b in self._botones.items():
            b.setChecked(clave == id_destino)

    def sincronizar_tema(self) -> None:
        """El botón de tema anuncia a qué modo lleva, no en cuál está.

        Con el sol dibujado en modo claro, la mitad de la gente entiende
        "estás en claro" y la otra mitad "apretá para ir a claro".
        Diciéndolo con palabras se acaba la duda.
        """
        oscuro = is_dark()
        texto = "  Tema claro" if oscuro else "  Tema oscuro"
        self.btn_tema.set_nombre_icono("sol" if oscuro else "luna")
        self._textos[self.btn_tema] = texto
        self.btn_tema.setText("" if self._compacta else texto)
        self.btn_tema.setToolTip(
            f"Cambiar a modo {'claro' if oscuro else 'oscuro'} (Ctrl+D)")

    def set_compacta(self, compacta: bool) -> None:
        """Colapsa a una tira de iconos, o vuelve a expandir."""
        if compacta == self._compacta:
            return
        self._compacta = compacta
        self.setFixedWidth(SIZE["rail"] if compacta else SIZE["sidebar"])

        for widget, texto in self._textos.items():
            widget.setText("" if compacta else texto)
            widget.setProperty("soloicono", "true" if compacta else "false")
            repolish(widget)

        self.lbl_seccion.setVisible(not compacta)
        self.lbl_marca.setVisible(not compacta)
        self.lbl_version.setVisible(not compacta)

    @property
    def compacta(self) -> bool:
        return self._compacta


# ═══════════════════════════════════════════════════════════════════════════════
#  Pantalla de inicio (launcher)
# ═══════════════════════════════════════════════════════════════════════════════

class PantallaInicio(QWidget):
    """El menú propiamente dicho: una tarjeta grande por herramienta.

    Señales:
      herramienta_elegida(str)  id del catálogo
      abrir_documento(str)      ruta de un documento reciente
      abrir_carpeta()
    """

    herramienta_elegida = pyqtSignal(str)
    abrir_documento = pyqtSignal(str)
    abrir_carpeta = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pantalla")
        self._columnas = 0

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        scroll = AreaScroll(margenes=(SPACE["2xl"], SPACE["2xl"],
                                      SPACE["2xl"], SPACE["2xl"]),
                            spacing=SPACE["lg"])
        lay = scroll.lay

        lay.addWidget(etiqueta("Herramientas", rol="display"))
        lay.addWidget(etiqueta(
            "Elegí con qué querés trabajar. Todo pasa en tu máquina: "
            "los documentos no salen de acá.", rol="cuerpo", wrap=True))
        lay.addSpacing(SPACE["sm"])

        self.grilla = QGridLayout()
        self.grilla.setSpacing(SPACE["lg"])
        self._tarjetas: list[TarjetaHerramienta] = []
        for herramienta in CATALOGO:
            tarjeta_h = TarjetaHerramienta(
                titulo=herramienta.titulo,
                descripcion=herramienta.descripcion,
                icono_nombre=herramienta.icono,
                etiqueta_pie=herramienta.chip,
                tono_pie=herramienta.tono_chip,
                habilitada=herramienta.disponible,
            )
            tarjeta_h.setToolTip(herramienta.atajo)
            tarjeta_h.activada.connect(
                lambda id_h=herramienta.id: self.herramienta_elegida.emit(id_h))
            self._tarjetas.append(tarjeta_h)
        lay.addLayout(self.grilla)

        lay.addSpacing(SPACE["md"])
        lay.addWidget(self._panel_recientes())
        lay.addStretch(1)

        raiz.addWidget(scroll)
        self._reacomodar(2)

    # -- recientes -----------------------------------------------------------
    def _panel_recientes(self) -> QWidget:
        marco = QFrame()
        marco.setObjectName("card")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        lay.setSpacing(SPACE["sm"])

        encabezado = QHBoxLayout()
        encabezado.setSpacing(SPACE["sm"])
        encabezado.addWidget(icono_label("reloj", 15, color="text_faint"))
        encabezado.addWidget(etiqueta("DOCUMENTOS RECIENTES", rol="seccion"))
        encabezado.addStretch(1)
        self.chip_total = Chip("0", tono="neutro", icono_nombre="documentos")
        encabezado.addWidget(self.chip_total)
        encabezado.addWidget(boton("Abrir carpeta", variant="plano",
                                   icono="carpeta-abierta",
                                   on_click=self.abrir_carpeta.emit))
        lay.addLayout(encabezado)

        self.lay_recientes = QVBoxLayout()
        self.lay_recientes.setSpacing(2)
        lay.addLayout(self.lay_recientes)

        self.lbl_sin_recientes = etiqueta(
            "Todavía no guardaste ningún documento.", rol="hint")
        lay.addWidget(self.lbl_sin_recientes)
        return marco

    def set_recientes(self, documentos: list[tuple[Path, str]], total: int) -> None:
        """documentos: hasta 3 pares (ruta, fecha ya formateada)."""
        while self.lay_recientes.count():
            item = self.lay_recientes.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        self.chip_total.set_texto(
            f"{total} documento{'s' if total != 1 else ''}")
        self.lbl_sin_recientes.setVisible(not documentos)

        for ruta, fecha in documentos[:3]:
            fila = boton(f"  {ruta.name}", variant="plano", icono="documento-firmado",
                         tooltip=f"{ruta}\n{fecha}", height=SIZE["btn_sm"],
                         on_click=lambda r=str(ruta): self.abrir_documento.emit(r))
            fila.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self.lay_recientes.addWidget(fila)

    # -- grilla responsive ---------------------------------------------------
    def _reacomodar(self, columnas: int) -> None:
        if columnas == self._columnas:
            return
        self._columnas = columnas
        for tarjeta_h in self._tarjetas:
            self.grilla.removeWidget(tarjeta_h)
        for i, tarjeta_h in enumerate(self._tarjetas):
            self.grilla.addWidget(tarjeta_h, i // columnas, i % columnas)
        for c in range(max(columnas, self.grilla.columnCount())):
            self.grilla.setColumnStretch(c, 1 if c < columnas else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        ancho = self.width()
        # Dos columnas por debajo de ~820 px dejan cada tarjeta en unos
        # 270 px: la descripción se parte en seis renglones y la tarjeta
        # se vuelve una pared de texto. Mejor una sola, más ancha.
        if ancho < BREAKPOINT["md"]:
            columnas = 1
        elif ancho < BREAKPOINT["xl"]:
            columnas = 2
        else:
            columnas = 3
        self._reacomodar(columnas)
