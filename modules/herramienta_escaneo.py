"""
modules/herramienta_escaneo.py
============================================================
Herramienta "Escanear a PDF": armar un documento página por página,
desde el escáner.

El flujo es el que uno hace en la vida real con un taco de hojas:
poner una, escanear, poner la siguiente, escanear… y al final guardar.
Cada página aparece en la lista apenas se digitaliza, con su miniatura,
y se puede reordenar, girar o descartar antes de armar el PDF.

También se puede **empezar desde un PDF que ya existe**. Es el caso de
"ya tenía el documento armado y me faltó escanear una hoja": en vez de
rehacerlo entero, se abre lo que hay y se le agregan las que falten. Las
páginas que vienen del PDF se copian tal cual —conservan su texto— y sólo
las escaneadas pasan por el convertidor de imágenes.

Reparto de responsabilidades
----------------------------
  modules/documento.py      qué páginas hay y en qué orden (sin Qt)
  modules/armado_pdf.py     escribe el PDF final (sin Qt)
  modules/previa.py         dibuja una página al tamaño en que se la ve
  modules/lista_paginas.py  la lista y la previa, compartidas con "Unir"
  modules/escaner_qt.py     el hilo que habla con WIA
  modules/imagen_pdf.py     imagen → PDF de una página
  este módulo               solamente lo propio de esta pantalla

Detalles que importan
---------------------
* **Se escanea a 300 DPI**, no a 600 como al firmar: acá se trata de
  documentos, y a 600 un PDF de 20 páginas se va a cientos de megas sin
  ganar nada legible.
* **Las páginas se identifican por id, no por posición**: la posición
  cambia con cada reordenamiento y usarla lleva a borrar la equivocada.
* Cómo se leen las imágenes sin comerse la RAM, y por qué la previa se
  pide al tamaño real del panel, está explicado en modules/previa.py.
"""

from __future__ import annotations

import logging
import os
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from modules.armado_pdf import ErrorArmado, abrir_en, armar_pdf, instantanea
from modules.dispositivos import (
    ErrorDispositivo,
    capacidades_escaner,
    verificar_escaneo_disponible,
)
from modules.documento import (
    ORIGEN_ESCANER,
    ORIGEN_IMAGEN,
    Documento,
    Pagina,
    con_extension_pdf,
    es_pdf,
    filtrar_soportados,
)
from modules.escaner_qt import DPI_DOCUMENTO, lanzar_escaneo, lanzar_lote
from modules.hojas import paginas_en_blanco
from modules.imagen_pdf import (
    CALIDAD_DEFECTO,
    LIMITE_CORREO_MB,
    borrar_si_existe,
    calidad,
    excede_limite,
    formatear_peso,
    opciones_calidad,
    siguiente_mas_liviana,
)
from modules.lista_paginas import PanelPaginas
from modules.previa import (
    limpiar_cache,
)
from modules.theme import SIZE, SPACE, repolish, theme_signals
from modules.ui import (
    BarraInferior,
    BarraSuperior,
    Chip,
    boton,
    boton_icono,
    etiqueta,
    icono_label,
    selector,
    separador_v,
)

log = logging.getLogger(__name__)

FILTRO_IMG = "Imágenes (*.png *.jpg *.jpeg *.bmp *.tiff *.tif)"
FILTRO_PDF = "Documentos PDF (*.pdf)"

#: Cómo entra el papel al escáner.
ORIGEN_CRISTAL = "cristal"
ORIGEN_LOTE = "lote"
ORIGEN_LOTE_DUPLEX = "lote_duplex"

NOMBRE_ORIGEN = {
    ORIGEN_CRISTAL: "Hoja por hoja (cristal)",
    ORIGEN_LOTE: "Todo el alimentador",
    ORIGEN_LOTE_DUPLEX: "Alimentador, doble faz",
}

TOOLTIP_ORIGEN = {
    ORIGEN_CRISTAL:
        "Una hoja por vez desde el cristal. Se abre el diálogo de Windows "
        "en cada página.",
    ORIGEN_LOTE:
        "Pasa todo el taco de corrido y agrega una página por hoja. "
        "Termina solo cuando se acaba el papel.",
    ORIGEN_LOTE_DUPLEX:
        "Pasa todo el taco leyendo las dos caras: dos páginas por hoja. "
        "Al terminar se ofrece quitar los dorsos que salgan en blanco.",
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker: arma el PDF en hilo secundario
# ═══════════════════════════════════════════════════════════════════════════════

class _WorkerArmarPDF(QThread):
    """Escribe el PDF en segundo plano.

    El trabajo de verdad vive en modules/armado_pdf.py, que no sabe de Qt:
    acá sólo se lo saca del hilo de la interfaz y se traducen sus avisos a
    señales. Así el armado se puede probar abriendo el PDF resultante, sin
    levantar una ventana ni un hilo.
    """

    progreso = pyqtSignal(int, str)     # (porcentaje 0-100, etiqueta)
    listo    = pyqtSignal(str)          # ruta del PDF final
    error    = pyqtSignal(str)          # mensaje + traceback

    def __init__(self, paginas: list[Pagina], destino: Path,
                 cal=CALIDAD_DEFECTO):
        super().__init__()              # SIN parent= a propósito
        self._calidad = calidad(cal)
        # Se congela la lista: el modelo puede cambiar mientras el hilo
        # trabaja si el usuario sigue tocando la pantalla.
        self._paginas = instantanea(paginas)
        self._destino = Path(destino)

    def run(self):
        try:
            armar_pdf(self._paginas, self._destino, cal=self._calidad,
                      progreso=self.progreso.emit)
            self.listo.emit(str(self._destino))
        except Exception as e:                           # noqa: BLE001
            tb = traceback.format_exc()
            log.error("Error al armar el PDF:\n%s", tb)
            self.error.emit(f"{e}\n\n─── Traceback completo ───\n{tb}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Estado vacío / zona de arrastre
# ═══════════════════════════════════════════════════════════════════════════════

class PanelVacio(QFrame):
    """Lo primero que se ve: qué hacer y cómo empezar."""

    escanear_pedido = pyqtSignal()
    importar_pedido = pyqtSignal()
    abrir_pdf_pedido = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panelVacio")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE["xl"], SPACE["3xl"], SPACE["xl"], SPACE["3xl"])
        lay.setSpacing(SPACE["md"])
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lay.addWidget(icono_label("escaner", 52, color="primary"), 0,
                      Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(SPACE["sm"])
        lay.addWidget(etiqueta("Todavía no hay páginas", rol="titulo",
                               align=Qt.AlignmentFlag.AlignCenter))
        lay.addWidget(etiqueta(
            "Poné la primera hoja en el escáner y empezá. Cada página que\n"
            "digitalices se va a agregar acá, y podés reordenarlas antes de guardar.",
            rol="cuerpo", wrap=True, align=Qt.AlignmentFlag.AlignCenter))
        lay.addSpacing(SPACE["md"])

        fila = QHBoxLayout()
        fila.setSpacing(SPACE["sm"])
        fila.addStretch(1)
        fila.addWidget(boton("Escanear la primera página", icono="escaner",
                             height=SIZE["btn_lg"], min_w=230,
                             on_click=self.escanear_pedido.emit))
        fila.addWidget(boton("Importar imágenes…", icono="imagen",
                             variant="secondary", height=SIZE["btn_lg"],
                             on_click=self.importar_pedido.emit))
        fila.addStretch(1)
        lay.addLayout(fila)

        lay.addSpacing(SPACE["md"])
        lay.addWidget(etiqueta(
            "¿Te faltaron hojas en un PDF que ya tenías?", rol="hint",
            align=Qt.AlignmentFlag.AlignCenter))
        fila2 = QHBoxLayout()
        fila2.addStretch(1)
        fila2.addWidget(boton(
            "Abrir un PDF y agregarle páginas…", icono="documento",
            variant="ghost",
            tooltip="Se abren sus páginas acá y podés escanear las que falten",
            on_click=self.abrir_pdf_pedido.emit))
        fila2.addStretch(1)
        lay.addLayout(fila2)

        lay.addSpacing(SPACE["sm"])
        lay.addWidget(etiqueta("…o arrastrá imágenes y PDF a esta ventana",
                               rol="hint", align=Qt.AlignmentFlag.AlignCenter))


# ═══════════════════════════════════════════════════════════════════════════════
#  Vista principal de la herramienta
# ═══════════════════════════════════════════════════════════════════════════════

class VistaEscanearAPdf(QWidget):
    """
    Señales:
      volver()               → el usuario pidió salir al menú
      documento_guardado(str) → se escribió el PDF (ruta absoluta)
    """

    volver = pyqtSignal()
    documento_guardado = pyqtSignal(str)

    def __init__(self, carpeta_destino: Path, parent=None,
                 calidad_inicial=CALIDAD_DEFECTO,
                 limite_mb: float = LIMITE_CORREO_MB):
        super().__init__(parent)
        self.setObjectName("pantalla")
        self.setAcceptDrops(True)

        self.carpeta_destino = Path(carpeta_destino)
        self._calidad_inicial = calidad_inicial
        self._limite_mb = limite_mb
        self.doc = Documento()
        self._worker: _WorkerArmarPDF | None = None
        self._lote = None
        self._escaneando = False
        self._temporales: list[str] = []
        #: Páginas que trajo el lote en curso, para ofrecer al final quitar
        #: los dorsos en blanco sólo de ESAS y no de todo el documento.
        self._ids_del_lote: list[int] = []

        # Se consulta una vez al abrir la herramienta: preguntarle al
        # escáner en cada refresco de pantalla lo despierta y tarda.
        self.capacidades = capacidades_escaner()
        self._origen = (ORIGEN_LOTE_DUPLEX if self.capacidades.duplex
                        else ORIGEN_LOTE if self.capacidades.alimentador
                        else ORIGEN_CRISTAL)

        self._construir_ui()
        self._refrescar()
        theme_signals.changed.connect(self._on_tema_cambiado)

    # ── Construcción ──────────────────────────────────────────────────────────

    def _construir_ui(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        self.cabecera = BarraSuperior("Escanear a PDF", icono_nombre="escaner")
        self.cabecera.agregar(boton("Volver al menú", variant="ghost",
                                    icono="chevron-izq",
                                    tooltip="Volver al menú de herramientas (Esc)",
                                    on_click=self._on_volver))
        raiz.addWidget(self.cabecera)

        raiz.addWidget(self._barra_acciones())

        # ── Cuerpo: lista + vista previa ──────────────────────────────────
        self.panel_vacio = PanelVacio()
        self.panel_vacio.escanear_pedido.connect(self._escanear)
        self.panel_vacio.importar_pedido.connect(self._importar)
        self.panel_vacio.abrir_pdf_pedido.connect(self._abrir_pdf)

        self.panel = PanelPaginas(self.doc, self.panel_vacio)
        self.panel.cambiado.connect(self._refrescar)
        raiz.addWidget(self.panel, 1)

        # ── Pie ───────────────────────────────────────────────────────────
        self.pie = BarraInferior("")
        self.chip_paginas = Chip("Sin páginas", tono="neutro",
                                 icono_nombre="documentos")
        self.pie.agregar(self.chip_paginas)

        self.barra_progreso = QProgressBar()
        self.barra_progreso.setFixedWidth(180)
        self.barra_progreso.setTextVisible(False)
        self.barra_progreso.hide()
        self.pie.agregar(self.barra_progreso)

        self.btn_guardar = boton("Guardar PDF", icono="guardar",
                                 height=SIZE["btn_lg"], min_w=170,
                                 enabled=False, on_click=self._guardar)
        self.pie.agregar(self.btn_guardar)
        raiz.addWidget(self.pie)

    def _barra_acciones(self) -> QWidget:
        marco = QFrame()
        marco.setObjectName("cabecera")
        lay = QHBoxLayout(marco)
        lay.setContentsMargins(SPACE["xl"], SPACE["sm"], SPACE["xl"], SPACE["sm"])
        lay.setSpacing(SPACE["sm"])

        self.btn_escanear = boton("Escanear", icono="escaner", min_w=150,
                                  tooltip="Digitalizar y agregar al final (Ctrl+N)",
                                  on_click=self._escanear)
        lay.addWidget(self.btn_escanear)

        # Cómo entra el papel. Las opciones se arman según lo que el
        # escáner dice saber hacer: ofrecer "alimentador" en una máquina
        # que sólo tiene cristal es un botón que devuelve error.
        self.combo_origen = selector(
            self._opciones_origen(), actual=self._origen,
            tooltips=dict(TOOLTIP_ORIGEN), on_change=self._on_origen, min_w=210)
        lay.addWidget(self.combo_origen)

        lay.addWidget(boton("Importar…", icono="imagen", variant="secondary",
                            tooltip="Agregar imágenes que ya tenés en el disco",
                            on_click=self._importar))

        self.btn_abrir_pdf = boton(
            "Abrir PDF…", icono="documento", variant="secondary",
            tooltip="Agregar al final las páginas de un PDF que ya tenés "
                    "(Ctrl+O)",
            on_click=self._abrir_pdf)
        lay.addWidget(self.btn_abrir_pdf)

        lay.addWidget(separador_v(26))

        self.btn_invertir = boton_icono(
            "refrescar", tooltip="Invertir el orden de todas las páginas",
            on_click=self._invertir)
        self.btn_rotar_todas = boton_icono(
            "rotar-der", tooltip="Girar todas las páginas 90° a la derecha",
            on_click=lambda: self._rotar_todas(90))
        self.btn_vaciar = boton_icono(
            "basura", tooltip="Quitar todas las páginas", on_click=self._vaciar)
        self.btn_vaciar.setProperty("danger", "true")
        repolish(self.btn_vaciar)
        for b in (self.btn_invertir, self.btn_rotar_todas, self.btn_vaciar):
            lay.addWidget(b)

        lay.addStretch(1)

        lay.addWidget(etiqueta("Calidad:", rol="hint"))
        opciones = opciones_calidad()
        self.combo_calidad = selector(
            [(c, n) for c, n, _ in opciones],
            actual=calidad(self._calidad_inicial).clave,
            tooltips={c: d for c, _, d in opciones},
            on_change=self._on_calidad, min_w=150)
        self._on_calidad(self.combo_calidad.currentData())
        lay.addWidget(self.combo_calidad)

        lay.addWidget(separador_v(26))

        self.chip_escaner = Chip("", tono="neutro", icono_nombre="escaner")
        lay.addWidget(self.chip_escaner)
        self._actualizar_chip_escaner()
        return marco

    # ── Estado de la vista ────────────────────────────────────────────────────

    def _refrescar(self) -> None:
        """Sincroniza todo lo que depende del modelo."""
        self.panel.refrescar()

        vacio = self.doc.vacio
        ocupado = self._escaneando or self._guardando
        self.panel.set_habilitado(not ocupado)

        self.btn_guardar.setEnabled(not vacio and not ocupado)
        for b in (self.btn_invertir, self.btn_rotar_todas, self.btn_vaciar):
            b.setEnabled(not vacio and not ocupado)
        self.btn_escanear.setEnabled(not ocupado)
        self.btn_abrir_pdf.setEnabled(not ocupado)

        self.chip_paginas.set_estado(
            self.doc.descripcion(),
            "primary" if not vacio else "neutro",
            "documentos")

        faltantes = self.doc.faltantes()
        if faltantes:
            self.pie.set_estado(
                f"{len(faltantes)} archivo(s) ya no están en el disco: "
                "quitá esas páginas antes de guardar.", rol="error", tono="err")
        elif self._escaneando:
            self.pie.set_estado("Escaneando…", tono="info")
        elif vacio:
            self.pie.set_estado("Escaneá, importá o abrí un PDF para empezar.")
        else:
            # La cantidad ya la dice el chip de al lado: acá va lo que
            # el usuario todavía puede hacer, no el mismo número repetido.
            partes = []
            giradas = self.doc.resumen_rotaciones()
            if giradas:
                partes.append(giradas)
            if self.doc.mixto:
                partes.append("las páginas del PDF se copian sin recomprimir")
            partes.append("Agregá la hoja siguiente, o guardá el documento.")
            self.pie.set_estado(".  ".join(partes))

    @property
    def _guardando(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _actualizar_chip_escaner(self) -> None:
        try:
            verificar_escaneo_disponible()
        except ErrorDispositivo:
            self.chip_escaner.set_estado("Escáner no disponible", "warn", "alerta")
            self.chip_escaner.setToolTip(
                "No se detectó un escáner. Igual podés importar imágenes "
                "o abrir un PDF desde el disco.")
            return

        cap = self.capacidades
        self.chip_escaner.set_estado(
            f"{cap.descripcion()} · {DPI_DOCUMENTO} DPI", "ok", "check-circulo")

        detalle = [f"Las páginas se digitalizan a {DPI_DOCUMENTO} DPI, que es "
                   "calidad de documento."]
        if cap.alimentador:
            detalle.append("Tiene alimentador: podés cargar el taco entero y "
                           "escanearlo de corrido.")
        if cap.duplex:
            detalle.append("Lee las dos caras en una sola pasada.")
        if not cap.conocidas:
            # No es lo mismo "sé que sólo tiene cristal" que "no me lo quiso
            # decir". Con la segunda, el usuario merece saber por qué no ve
            # las opciones de alimentador.
            detalle.append("El driver no informa si tiene alimentador, así "
                           "que se ofrece sólo el cristal.")
        self.chip_escaner.setToolTip("\n\n".join(detalle))

    def _opciones_origen(self) -> list[tuple[str, str]]:
        """Las formas de escanear que este aparato admite de verdad."""
        cap = self.capacidades
        opciones = []
        if cap.cristal or not cap.alimentador:
            opciones.append((ORIGEN_CRISTAL, NOMBRE_ORIGEN[ORIGEN_CRISTAL]))
        if cap.alimentador:
            opciones.append((ORIGEN_LOTE, NOMBRE_ORIGEN[ORIGEN_LOTE]))
        if cap.duplex:
            opciones.append((ORIGEN_LOTE_DUPLEX,
                             NOMBRE_ORIGEN[ORIGEN_LOTE_DUPLEX]))
        return opciones

    def _on_origen(self, clave) -> None:
        self._origen = clave or ORIGEN_CRISTAL
        self.combo_origen.setToolTip(TOOLTIP_ORIGEN.get(self._origen, ""))
        if hasattr(self, "btn_escanear"):
            self.btn_escanear.setText(
                "Escanear" if self._origen == ORIGEN_CRISTAL
                else "Escanear el taco")

    # ── Acciones sobre el modelo ──────────────────────────────────────────────

    def _rotar_todas(self, grados: int) -> None:
        self.doc.rotar_todas(grados)
        self._refrescar()

    def _invertir(self) -> None:
        self.doc.invertir()
        self._refrescar()

    def _vaciar(self) -> None:
        if self.doc.vacio:
            return
        respuesta = QMessageBox.question(
            self, "Vaciar el documento",
            f"¿Quitar las {self.doc.total} páginas y empezar de nuevo?\n\n"
            "Los archivos escaneados quedan en la carpeta temporal hasta "
            "que cierres la herramienta. Los PDF que abriste no se tocan.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if respuesta == QMessageBox.StandardButton.Yes:
            self.doc.limpiar()
            self.panel.marcar(None)
            # Esas páginas ya no se pueden ver: no tiene sentido seguir
            # ocupando el presupuesto del cache con ellas.
            limpiar_cache()
            self._refrescar()

    # ── Entrada de páginas ────────────────────────────────────────────────────

    def _escanear(self) -> None:
        if self._escaneando:
            QMessageBox.information(
                self, "Escaneo en curso",
                "Ya hay un escaneo abierto. Terminalo o cancelalo antes de "
                "empezar otro.")
            return

        try:
            verificar_escaneo_disponible()
        except ErrorDispositivo as e:
            QMessageBox.warning(self, "No se puede escanear", e.texto_completo())
            self._actualizar_chip_escaner()
            return

        self._escaneando = True
        self._refrescar()

        if self._origen == ORIGEN_CRISTAL:
            lanzar_escaneo(
                dpi=DPI_DOCUMENTO,
                al_completar=self._on_escaneo_listo,
                al_cancelar=self._on_escaneo_cancelado,
                al_fallar=self._on_escaneo_error,
            )
            return

        self._ids_del_lote = []
        self.barra_progreso.setRange(0, 0)      # indeterminada: no se sabe
        self.barra_progreso.show()              # cuántas hojas hay en la bandeja
        self._lote = lanzar_lote(
            dpi=DPI_DOCUMENTO,
            duplex=(self._origen == ORIGEN_LOTE_DUPLEX),
            al_llegar_pagina=self._on_pagina_del_lote,
            al_completar=self._on_lote_completado,
            al_parcial=self._on_lote_parcial,
            al_cancelar=self._on_lote_cancelado,
            al_fallar=self._on_escaneo_error,
        )

    # ── Lote del alimentador ──────────────────────────────────────────────────

    def _on_pagina_del_lote(self, ruta: str, numero: int) -> None:
        """Cada hoja se agrega apenas llega, sin esperar al final del taco.

        Con 30 hojas el lote son varios minutos: mostrarlas recién al
        terminar dejaría la pantalla muda todo ese rato.
        """
        self._temporales.append(ruta)
        pagina = self.doc.agregar(ruta, origen=ORIGEN_ESCANER, temporal=True)
        self._ids_del_lote.append(pagina.id)
        self.panel.marcar(pagina.id)
        self._refrescar()
        self.panel.ir_a_la_ultima()
        self.pie.set_estado(f"Escaneando… {numero} página(s) hasta ahora.",
                            tono="info")

    def _terminar_lote(self) -> None:
        self._escaneando = False
        self._lote = None
        self.barra_progreso.setRange(0, 100)
        self.barra_progreso.hide()

    def _on_lote_completado(self, cuantas: int) -> None:
        self._terminar_lote()
        self._refrescar()
        self._ofrecer_quitar_dorsos()
        self.btn_escanear.setFocus()

    def _on_lote_cancelado(self) -> None:
        self._terminar_lote()
        self._refrescar()

    def _on_lote_parcial(self, error, rutas) -> None:
        """Se cortó a mitad del taco. Las páginas ya están en la lista."""
        self._terminar_lote()
        self._refrescar()
        traidas = len(self._ids_del_lote)
        texto = error.texto_completo() if isinstance(error, ErrorDispositivo) \
            else str(error)
        QMessageBox.warning(
            self, "El lote se interrumpió",
            f"{texto}\n\nLas {traidas} página(s) que ya se habían escaneado "
            "quedan en la lista. Podés cargar el resto del taco y seguir "
            "escaneando desde donde quedó.")
        self._actualizar_chip_escaner()

    def _ofrecer_quitar_dorsos(self) -> None:
        """Al escanear a doble faz, las hojas impresas de un solo lado dejan
        un dorso vacío. Se ofrece sacarlos, nunca se hace solo.

        Que sea una pregunta y no un automatismo es deliberado: la
        detección mira cuánta tinta hay en la hoja y no puede distinguir
        una página realmente vacía de una que sólo tiene un número de
        folio. Equivocarse en silencio sería borrar trabajo del usuario.
        """
        if self._origen != ORIGEN_LOTE_DUPLEX or not self._ids_del_lote:
            return

        del_lote = [p for p in self.doc.paginas if p.id in set(self._ids_del_lote)]
        vacias = paginas_en_blanco(del_lote)
        if not vacias:
            return

        numeros = ", ".join(str(self.doc.indice_de(p.id) + 1) for p in vacias[:12])
        if len(vacias) > 12:
            numeros += f" y {len(vacias) - 12} más"

        respuesta = QMessageBox.question(
            self, "Dorsos en blanco",
            f"De las {len(del_lote)} páginas del taco, {len(vacias)} parecen "
            f"estar en blanco:\n\npáginas {numeros}\n\n"
            "Son los dorsos de las hojas impresas de un solo lado. "
            "¿Las quito del documento?\n\n"
            "Podés revisarlas en la lista antes de decidir: las que tengan "
            "aunque sea un sello o un número de página no aparecen acá.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if respuesta == QMessageBox.StandardButton.Yes:
            self.doc.quitar_varias([p.id for p in vacias])
            self.panel.marcar(None)
            self._refrescar()
            self.pie.set_estado(
                f"Se quitaron {len(vacias)} páginas en blanco.", tono="ok")

    def _on_escaneo_listo(self, ruta: str) -> None:
        self._escaneando = False
        self._temporales.append(ruta)
        pagina = self.doc.agregar(ruta, origen=ORIGEN_ESCANER, temporal=True)
        self.panel.marcar(pagina.id)
        self._refrescar()
        self.panel.ir_a_la_ultima()
        # Enfocar el botón deja lista la próxima hoja: el usuario está
        # frente al escáner y sólo tiene que apretar Enter.
        self.btn_escanear.setFocus()

    def _on_escaneo_cancelado(self) -> None:
        self._escaneando = False
        self._refrescar()

    def _on_escaneo_error(self, error) -> None:
        self._escaneando = False
        self._refrescar()
        texto = (error.texto_completo() if isinstance(error, ErrorDispositivo)
                 else str(error))
        log.warning("Error de escaneo: %s", texto)
        QMessageBox.warning(self, "Error al digitalizar", texto)
        self._actualizar_chip_escaner()

    def _importar(self) -> None:
        rutas, _ = QFileDialog.getOpenFileNames(
            self, "Elegir imágenes para el documento",
            os.path.expanduser("~"), FILTRO_IMG)
        if rutas:
            self._agregar(sorted(rutas))

    def _abrir_pdf(self) -> None:
        """Abre un PDF y suma sus páginas al final.

        Es el caso de "ya tenía el documento y me faltó escanear una hoja":
        en vez de empezar de cero, se abre lo que hay y se le agrega.
        """
        rutas, _ = QFileDialog.getOpenFileNames(
            self, "Abrir un PDF para agregarle páginas",
            os.path.expanduser("~"), FILTRO_PDF)
        if rutas:
            self._agregar(rutas)

    def _agregar(self, rutas: list[str]) -> None:
        """Suma imágenes y/o PDF al final del documento, en el orden dado."""
        validas = filtrar_soportados(rutas)
        if not validas:
            QMessageBox.information(
                self, "Nada para agregar",
                "Ninguno de los archivos es algo que pueda abrir.\n\n"
                "Formatos admitidos: PDF, PNG, JPG, BMP y TIFF.")
            return

        ultima: int | None = None
        problemas: list[str] = []
        for ruta in validas:
            if es_pdf(ruta):
                try:
                    abrir_en(self.doc, ruta)
                except ErrorArmado as e:
                    problemas.append(str(e))
                    continue
                ultima = self.doc.paginas[-1].id if self.doc.paginas else None
            else:
                pagina = self.doc.agregar(ruta, temporal=False,
                                          origen=ORIGEN_IMAGEN)
                ultima = pagina.id

        if ultima is not None:
            self.panel.marcar(ultima)
        self._refrescar()
        self.panel.ir_a_la_ultima()

        if problemas:
            QMessageBox.warning(self, "No se pudieron abrir todos los archivos",
                                "\n\n".join(problemas))

    # ── Arrastrar y soltar ────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() and filtrar_soportados(
                u.toLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        rutas = [u.toLocalFile() for u in event.mimeData().urls()]
        validas = filtrar_soportados(rutas)
        if validas:
            self._agregar(sorted(validas))
            event.acceptProposedAction()

    # ── Guardado ──────────────────────────────────────────────────────────────

    def _guardar(self) -> None:
        if self.doc.vacio or self._guardando:
            return

        faltantes = self.doc.faltantes()
        if faltantes:
            QMessageBox.warning(
                self, "Faltan archivos",
                f"{len(faltantes)} página(s) apuntan a archivos que ya no "
                "están en el disco.\n\nQuitalas de la lista antes de guardar.")
            return

        self.carpeta_destino.mkdir(parents=True, exist_ok=True)
        sugerido = self.carpeta_destino / self.doc.nombre_sugerido()
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar el PDF", str(sugerido), "Documentos PDF (*.pdf)")
        if not ruta:
            return

        destino = Path(ruta).parent / con_extension_pdf(Path(ruta).name)

        self.barra_progreso.setValue(0)
        self.barra_progreso.show()
        worker = _WorkerArmarPDF(list(self.doc.paginas), destino,
                                 self.combo_calidad.currentData())
        self._worker = worker
        worker.progreso.connect(self._on_progreso)
        worker.listo.connect(self._on_guardado)
        worker.error.connect(self._on_error_guardado)
        worker.finished.connect(self._on_worker_termino)
        worker.start()
        self._refrescar()

    def _on_progreso(self, porcentaje: int, etapa: str) -> None:
        self.barra_progreso.setValue(porcentaje)
        self.pie.set_estado(etapa, tono="info")

    def _on_calidad(self, clave) -> None:
        cal = calidad(clave)
        self.combo_calidad.setToolTip(cal.descripcion)

    def _on_guardado(self, ruta: str) -> None:
        self.barra_progreso.hide()
        destino = Path(ruta)
        nombre = destino.name
        try:
            peso = destino.stat().st_size
        except OSError:
            peso = 0

        self.pie.set_estado(f"Guardado: {nombre}  ·  {formatear_peso(peso)}",
                            rol="ok", tono="ok")
        self.documento_guardado.emit(ruta)

        if peso and excede_limite(peso, self._limite_mb):
            self._avisar_demasiado_grande(peso)

        respuesta = QMessageBox.question(
            self, "PDF guardado",
            f"Se guardó «{nombre}» ({formatear_peso(peso)}) con "
            f"{self.doc.total} página(s).\n\n"
            "¿Querés empezar un documento nuevo?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if respuesta == QMessageBox.StandardButton.Yes:
            self.doc.limpiar()
            self.panel.marcar(None)
            limpiar_cache()
        self._refrescar()

    def _avisar_demasiado_grande(self, peso: int) -> None:
        """Un PDF que no entra como adjunto es medio inservible, y darse
        cuenta al adjuntarlo obliga a rehacer todo el escaneo."""
        mas_liviana = siguiente_mas_liviana(self.combo_calidad.currentData())
        texto = (f"El documento pesa {formatear_peso(peso)} y el límite de "
                 f"adjunto habitual es de {self._limite_mb} MB.")
        if mas_liviana is None:
            texto += ("\n\nYa está en la calidad más liviana: convendría "
                      "partirlo en varios documentos.")
        else:
            texto += (f"\n\nProbá con la calidad «{mas_liviana.nombre}» y "
                      "volvé a guardar: " + mas_liviana.descripcion)
        if self.doc.tiene_pdf:
            texto += ("\n\nOjo: la calidad sólo afecta a las páginas "
                      "escaneadas o importadas como imagen. Las que vienen "
                      "de un PDF se copian tal cual, para no perder el texto.")
        QMessageBox.warning(self, "El archivo es grande", texto)

    def _on_error_guardado(self, mensaje: str) -> None:
        self.barra_progreso.hide()
        log.error("Fallo al armar el PDF: %s", mensaje)
        cuadro = QMessageBox(self)
        cuadro.setIcon(QMessageBox.Icon.Warning)
        cuadro.setWindowTitle("No se pudo guardar el PDF")
        cuadro.setText(mensaje.split("\n\n")[0])
        cuadro.setDetailedText(mensaje)
        cuadro.exec()
        self.pie.set_estado("No se pudo guardar el documento.", rol="error",
                            tono="err")

    def _on_worker_termino(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self._refrescar()

    # ── Eventos ───────────────────────────────────────────────────────────────

    def _on_tema_cambiado(self, _modo: str) -> None:
        self._refrescar()

    def _on_volver(self) -> None:
        if self._guardando:
            QMessageBox.information(
                self, "Guardado en curso",
                "Esperá a que termine de armarse el PDF.")
            return
        if not self.doc.vacio:
            respuesta = QMessageBox.question(
                self, "Salir de la herramienta",
                f"Tenés {self.doc.total} página(s) sin guardar.\n\n"
                "Si salís ahora se descartan. ¿Salir igual?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if respuesta != QMessageBox.StandardButton.Yes:
                return
        self.volver.emit()

    def keyPressEvent(self, event):
        ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if event.key() == Qt.Key.Key_Escape:
            self._on_volver()
            return
        if ctrl and event.key() == Qt.Key.Key_N:
            self._escanear()
            return
        if ctrl and event.key() == Qt.Key.Key_O:
            self._abrir_pdf()
            return
        if ctrl and event.key() == Qt.Key.Key_S:
            self._guardar()
            return
        if ctrl and self.panel.seleccionada is not None:
            if event.key() == Qt.Key.Key_Up:
                self.panel.mover(self.panel.seleccionada, -1)
                return
            if event.key() == Qt.Key.Key_Down:
                self.panel.mover(self.panel.seleccionada, 1)
                return
        super().keyPressEvent(event)

    def limpiar_temporales(self) -> None:
        """Borra los escaneos temporales que esta herramienta creó.

        Se llama al cerrar la app o al salir de la herramienta. Las
        imágenes que el usuario importó y los PDF que abrió no se tocan.
        """
        for ruta in self._temporales:
            borrar_si_existe(ruta)
        self._temporales.clear()

    def closeEvent(self, event):
        try:
            theme_signals.changed.disconnect(self._on_tema_cambiado)
        except (TypeError, RuntimeError):
            pass
        self.limpiar_temporales()
        limpiar_cache()
        super().closeEvent(event)
