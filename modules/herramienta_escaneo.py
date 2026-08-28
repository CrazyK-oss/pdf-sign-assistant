"""
modules/herramienta_escaneo.py
============================================================
Herramienta "Escanear a PDF": armar un documento nuevo, página por
página, desde el escáner.

El flujo es el que uno hace en la vida real con un taco de hojas:
poner una, escanear, poner la siguiente, escanear… y al final guardar.
Cada página aparece en la lista apenas se digitaliza, con su miniatura,
y se puede reordenar, girar o descartar antes de armar el PDF.

Reparto de responsabilidades
----------------------------
  modules/documento.py    qué páginas hay y en qué orden (sin Qt)
  modules/armado_pdf.py   escribe el PDF final (sin Qt)
  modules/previa.py       dibuja una página al tamaño en que se la ve
  modules/escaner_qt.py   el hilo que habla con WIA
  modules/imagen_pdf.py   imagen → PDF de una página
  este módulo             solamente la pantalla

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
    QLabel,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from modules.armado_pdf import armar_pdf, instantanea
from modules.dispositivos import ErrorDispositivo, verificar_escaneo_disponible
from modules.documento import (
    ORIGEN_ESCANER,
    ORIGEN_IMAGEN,
    Documento,
    Pagina,
    con_extension_pdf,
    filtrar_imagenes,
)
from modules.escaner_qt import DPI_DOCUMENTO, lanzar_escaneo
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
from modules.previa import (
    LADO_MINIATURA,
    dimensiones,
    escalar_para,
    limpiar_cache,
)
from modules.theme import BREAKPOINT, SIZE, SPACE, repolish, theme_signals
from modules.ui import (
    AreaScroll,
    Aviso,
    BarraInferior,
    BarraSuperior,
    Chip,
    FilaAdaptable,
    boton,
    boton_icono,
    etiqueta,
    icono_label,
    selector,
    separador_v,
    tarjeta,
)

log = logging.getLogger(__name__)

FILTRO_IMG = "Imágenes (*.png *.jpg *.jpeg *.bmp *.tiff *.tif)"


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
#  Fila de una página
# ═══════════════════════════════════════════════════════════════════════════════

class FilaEscaneada(QFrame):
    """Una página de la lista: miniatura, datos y acciones."""

    seleccionada = pyqtSignal(int)
    subir_pedido = pyqtSignal(int)
    bajar_pedido = pyqtSignal(int)
    rotar_pedido = pyqtSignal(int, int)
    quitar_pedido = pyqtSignal(int)

    def __init__(self, pagina: Pagina, numero: int, parent=None):
        super().__init__(parent)
        self.id_pagina = pagina.id
        self.setObjectName("filaPagina")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
        lay.setSpacing(SPACE["md"])

        self.lbl_numero = QLabel()
        self.lbl_numero.setObjectName("numeroPagina")
        self.lbl_numero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_numero.setFixedWidth(34)
        lay.addWidget(self.lbl_numero, 0, Qt.AlignmentFlag.AlignVCenter)

        self.lbl_thumb = QLabel()
        self.lbl_thumb.setObjectName("miniatura")
        self.lbl_thumb.setFixedSize(72, LADO_MINIATURA)
        self.lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_thumb, 0, Qt.AlignmentFlag.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(3)
        col.addStretch(1)
        self.lbl_titulo = etiqueta("", rol="subtitulo")
        self.lbl_detalle = etiqueta("", rol="hint")
        col.addWidget(self.lbl_titulo)
        col.addWidget(self.lbl_detalle)
        col.addStretch(1)
        lay.addLayout(col, 1)

        # Acciones. Todas con tooltip: el icono es su única etiqueta.
        self.btn_subir = boton_icono(
            "arriba", tooltip="Subir esta página", lado=SIZE["btn_sm"],
            tamano_icono=15, on_click=lambda: self.subir_pedido.emit(self.id_pagina))
        self.btn_bajar = boton_icono(
            "abajo", tooltip="Bajar esta página", lado=SIZE["btn_sm"],
            tamano_icono=15, on_click=lambda: self.bajar_pedido.emit(self.id_pagina))
        self.btn_rot_izq = boton_icono(
            "rotar-izq", tooltip="Girar 90° a la izquierda", lado=SIZE["btn_sm"],
            tamano_icono=15,
            on_click=lambda: self.rotar_pedido.emit(self.id_pagina, -90))
        self.btn_rot_der = boton_icono(
            "rotar-der", tooltip="Girar 90° a la derecha", lado=SIZE["btn_sm"],
            tamano_icono=15,
            on_click=lambda: self.rotar_pedido.emit(self.id_pagina, 90))
        self.btn_quitar = boton_icono(
            "basura", tooltip="Quitar esta página del documento",
            lado=SIZE["btn_sm"], tamano_icono=15,
            on_click=lambda: self.quitar_pedido.emit(self.id_pagina))
        self.btn_quitar.setProperty("danger", "true")
        repolish(self.btn_quitar)

        acciones = QHBoxLayout()
        acciones.setSpacing(SPACE["xs"])
        for b in (self.btn_subir, self.btn_bajar):
            acciones.addWidget(b)
        acciones.addWidget(separador_v(SIZE["btn_sm"] - 6))
        for b in (self.btn_rot_izq, self.btn_rot_der, self.btn_quitar):
            acciones.addWidget(b)
        lay.addLayout(acciones, 0)

    def actualizar(self, pagina: Pagina, numero: int, total: int,
                   activa: bool) -> None:
        self.lbl_numero.setText(str(numero))
        self.btn_subir.setEnabled(numero > 1)
        self.btn_bajar.setEnabled(numero < total)

        self.setProperty("activa", "true" if activa else "false")
        repolish(self)

        if not pagina.existe:
            self.lbl_thumb.clear()
            self.lbl_titulo.setText(pagina.nombre)
            self.lbl_detalle.setText("El archivo ya no está en el disco")
            self.lbl_detalle.setProperty("rol", "error")
            repolish(self.lbl_detalle)
            return

        pm = escalar_para(self.lbl_thumb, pagina, tope=LADO_MINIATURA * 4)
        if pm.isNull():
            self.lbl_thumb.clear()
        else:
            self.lbl_thumb.setPixmap(pm)

        origen = "Escaneada" if pagina.origen == "escaner" else "Importada"
        self.lbl_titulo.setText(f"Página {numero}")

        ancho, alto = dimensiones(pagina)
        partes = [origen]
        if ancho and alto:
            partes.append(f"{ancho}×{alto} px")
        try:
            partes.append(formatear_peso(pagina.ruta.stat().st_size))
        except OSError:
            pass
        if pagina.rotacion:
            partes.append(f"girada {pagina.rotacion}°")
        self.lbl_detalle.setText("  ·  ".join(partes))
        self.lbl_detalle.setProperty("rol", "hint")
        repolish(self.lbl_detalle)

    def mousePressEvent(self, event):
        self.seleccionada.emit(self.id_pagina)
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        self.seleccionada.emit(self.id_pagina)
        super().focusInEvent(event)


# ═══════════════════════════════════════════════════════════════════════════════
#  Estado vacío / zona de arrastre
# ═══════════════════════════════════════════════════════════════════════════════

class PanelVacio(QFrame):
    """Lo primero que se ve: qué hacer y cómo empezar."""

    escanear_pedido = pyqtSignal()
    importar_pedido = pyqtSignal()

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

        lay.addSpacing(SPACE["sm"])
        lay.addWidget(etiqueta("…o arrastrá las imágenes a esta ventana",
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
        self._filas: dict[int, FilaEscaneada] = {}
        self._seleccionada: int | None = None
        self._worker: _WorkerArmarPDF | None = None
        self._escaneando = False
        self._temporales: list[str] = []

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
        self.cuerpo = FilaAdaptable(breakpoint_px=BREAKPOINT["lg"],
                                    spacing=SPACE["lg"])
        self.cuerpo.setContentsMargins(SPACE["xl"], SPACE["lg"],
                                       SPACE["xl"], SPACE["lg"])
        self.cuerpo.orientacion_cambiada.connect(self._on_apilado)

        self.pila = QStackedWidget()
        self.panel_vacio = PanelVacio()
        self.panel_vacio.escanear_pedido.connect(self._escanear)
        self.panel_vacio.importar_pedido.connect(self._importar)

        self.scroll = AreaScroll(margenes=(0, 0, SPACE["sm"], 0),
                                 spacing=SPACE["sm"])
        self.lay_filas = self.scroll.lay
        self.lay_filas.addStretch(1)

        self.pila.addWidget(self.panel_vacio)   # índice 0
        self.pila.addWidget(self.scroll)        # índice 1
        self.cuerpo.agregar(self.pila, 3)

        self.panel_previa = self._panel_previa()
        self.cuerpo.agregar(self.panel_previa, 2)
        raiz.addWidget(self.cuerpo, 1)

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

        self.btn_escanear = boton("Escanear página", icono="escaner",
                                  min_w=180,
                                  tooltip="Digitalizar una hoja y agregarla al final "
                                          "(Ctrl+N)",
                                  on_click=self._escanear)
        lay.addWidget(self.btn_escanear)

        lay.addWidget(boton("Importar…", icono="imagen", variant="secondary",
                            tooltip="Agregar imágenes que ya tenés en el disco",
                            on_click=self._importar))

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

    def _panel_previa(self) -> QWidget:
        marco, lay = tarjeta(padding=SPACE["lg"], spacing=SPACE["md"])
        marco.setMinimumWidth(280)
        marco.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        encabezado = QHBoxLayout()
        encabezado.setSpacing(SPACE["sm"])
        encabezado.addWidget(icono_label("ojo", SIZE["icono"], color="text_faint"))
        encabezado.addWidget(etiqueta("VISTA PREVIA", rol="seccion"))
        encabezado.addStretch(1)
        lay.addLayout(encabezado)

        self.lbl_previa = QLabel()
        self.lbl_previa.setObjectName("lienzoPagina")
        self.lbl_previa.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_previa.setMinimumHeight(260)
        self.lbl_previa.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Expanding)
        lay.addWidget(self.lbl_previa, 1)

        self.lbl_previa_info = etiqueta("", rol="hint", wrap=True,
                                        align=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_previa_info)

        self.aviso_previa = Aviso("", tono="warn")
        self.aviso_previa.hide()
        lay.addWidget(self.aviso_previa)
        return marco

    # ── Estado de la vista ────────────────────────────────────────────────────

    def _refrescar(self) -> None:
        """Reconstruye la lista y sincroniza todo lo que depende del modelo."""
        self._sincronizar_filas()

        vacio = self.doc.vacio
        self.pila.setCurrentIndex(0 if vacio else 1)
        self.panel_previa.setVisible(not vacio and not self.cuerpo.apilado)

        ocupado = self._escaneando or self._guardando
        self.btn_guardar.setEnabled(not vacio and not ocupado)
        for b in (self.btn_invertir, self.btn_rotar_todas, self.btn_vaciar):
            b.setEnabled(not vacio and not ocupado)
        self.btn_escanear.setEnabled(not ocupado)

        # Chip y mensaje de estado
        self.chip_paginas.set_estado(
            self.doc.descripcion(),
            "primary" if not vacio else "neutro",
            "documentos")

        faltantes = self.doc.faltantes()
        if faltantes:
            self.pie.set_estado(
                f"{len(faltantes)} imagen(es) ya no están en el disco: "
                "quitalas antes de guardar.", rol="error", tono="err")
        elif self._escaneando:
            self.pie.set_estado("Escaneando…", tono="info")
        elif vacio:
            self.pie.set_estado("Escaneá o importá la primera página para empezar.")
        else:
            # La cantidad ya la dice el chip de al lado: acá va lo que
            # el usuario todavía puede hacer, no el mismo número repetido.
            giradas = self.doc.resumen_rotaciones()
            mensaje = "Agregá la hoja siguiente, o guardá el documento."
            if giradas:
                mensaje = f"{giradas}.  {mensaje}"
            self.pie.set_estado(mensaje)

        self._refrescar_previa()

    @property
    def _guardando(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _sincronizar_filas(self) -> None:
        """Crea, reordena o descarta filas hasta que coincidan con el modelo.

        Se reutilizan los widgets existentes en vez de reconstruir la lista
        entera: con 30 páginas, rehacerla en cada rotación se nota.
        """
        vivos = {p.id for p in self.doc.paginas}
        for id_pagina in list(self._filas):
            if id_pagina not in vivos:
                fila = self._filas.pop(id_pagina)
                self.lay_filas.removeWidget(fila)
                fila.setParent(None)
                fila.deleteLater()

        total = self.doc.total
        for indice, pagina in enumerate(self.doc.paginas):
            fila = self._filas.get(pagina.id)
            if fila is None:
                fila = FilaEscaneada(pagina, indice + 1)
                fila.seleccionada.connect(self._seleccionar)
                fila.subir_pedido.connect(lambda i: self._mover(i, -1))
                fila.bajar_pedido.connect(lambda i: self._mover(i, 1))
                fila.rotar_pedido.connect(self._rotar)
                fila.quitar_pedido.connect(self._quitar)
                self._filas[pagina.id] = fila
            # insertWidget respeta el orden aunque la fila ya estuviera:
            # Qt la saca de su posición previa antes de reinsertarla.
            self.lay_filas.insertWidget(indice, fila)
            fila.actualizar(pagina, indice + 1, total,
                            activa=pagina.id == self._seleccionada)

    def _refrescar_previa(self) -> None:
        # resizeEvent puede llegar antes de que el panel exista.
        if not hasattr(self, "lbl_previa"):
            return
        pagina = (self.doc.pagina(self._seleccionada)
                  if self._seleccionada is not None else None)
        if pagina is None and self.doc.paginas:
            pagina = self.doc.paginas[0]
            self._seleccionada = pagina.id

        if pagina is None:
            self.lbl_previa.clear()
            self.lbl_previa_info.setText("")
            self.aviso_previa.hide()
            return

        pm = escalar_para(self.lbl_previa, pagina)
        if pm.isNull():
            self.lbl_previa.setText("No se pudo leer la imagen")
            self.aviso_previa.mostrar(
                "El archivo de esta página ya no está o no se puede leer. "
                "Quitala de la lista y volvé a escanearla.", "err")
        else:
            self.lbl_previa.setPixmap(pm)
            self.aviso_previa.setVisible(False)

        numero = self.doc.indice_de(pagina.id) + 1
        ancho, alto = dimensiones(pagina)
        detalle = f"Página {numero} de {self.doc.total}"
        if ancho and alto:
            detalle += f"  ·  {ancho}×{alto} px"
        if pagina.rotacion:
            detalle += f"  ·  girada {pagina.rotacion}°"
        self.lbl_previa_info.setText(detalle)

    def _actualizar_chip_escaner(self) -> None:
        try:
            verificar_escaneo_disponible()
        except ErrorDispositivo:
            self.chip_escaner.set_estado("Escáner no disponible", "warn", "alerta")
            self.chip_escaner.setToolTip(
                "No se detectó un escáner. Igual podés importar imágenes "
                "desde el disco.")
        else:
            self.chip_escaner.set_estado(f"Escáner listo · {DPI_DOCUMENTO} DPI",
                                         "ok", "check-circulo")
            self.chip_escaner.setToolTip(
                f"Las páginas se digitalizan a {DPI_DOCUMENTO} DPI, que es "
                "calidad de documento.")

    # ── Acciones sobre el modelo ──────────────────────────────────────────────

    def _seleccionar(self, id_pagina: int) -> None:
        if id_pagina == self._seleccionada:
            return
        self._seleccionada = id_pagina
        for pid, fila in self._filas.items():
            fila.setProperty("activa", "true" if pid == id_pagina else "false")
            repolish(fila)
        self._refrescar_previa()

    def _mover(self, id_pagina: int, desplazamiento: int) -> None:
        if self.doc.mover(id_pagina, desplazamiento):
            self._seleccionada = id_pagina
            self._refrescar()

    def _rotar(self, id_pagina: int, grados: int) -> None:
        if self.doc.rotar(id_pagina, grados):
            self._seleccionada = id_pagina
            self._refrescar()

    def _rotar_todas(self, grados: int) -> None:
        self.doc.rotar_todas(grados)
        self._refrescar()

    def _invertir(self) -> None:
        self.doc.invertir()
        self._refrescar()

    def _quitar(self, id_pagina: int) -> None:
        quitada = self.doc.quitar(id_pagina)
        if quitada is None:
            return
        if self._seleccionada == id_pagina:
            self._seleccionada = None
        # El temporal se borra al cerrar, no ahora: si el usuario se
        # arrepiente, todavía puede volver a importarlo desde /tmp.
        self._refrescar()

    def _vaciar(self) -> None:
        if self.doc.vacio:
            return
        respuesta = QMessageBox.question(
            self, "Vaciar el documento",
            f"¿Quitar las {self.doc.total} páginas y empezar de nuevo?\n\n"
            "Los archivos escaneados quedan en la carpeta temporal hasta "
            "que cierres la herramienta.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if respuesta == QMessageBox.StandardButton.Yes:
            self.doc.limpiar()
            self._seleccionada = None
            # Esas imágenes ya no se pueden ver: no tiene sentido seguir
            # ocupando el presupuesto del cache con ellas.
            limpiar_cache()
            self._refrescar()

    # ── Entrada de imágenes ───────────────────────────────────────────────────

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
        lanzar_escaneo(
            dpi=DPI_DOCUMENTO,
            al_completar=self._on_escaneo_listo,
            al_cancelar=self._on_escaneo_cancelado,
            al_fallar=self._on_escaneo_error,
        )

    def _on_escaneo_listo(self, ruta: str) -> None:
        self._escaneando = False
        self._temporales.append(ruta)
        pagina = self.doc.agregar(ruta, origen=ORIGEN_ESCANER, temporal=True)
        self._seleccionada = pagina.id
        self._refrescar()
        self._ir_a_la_ultima()
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
            self._agregar_imagenes(sorted(rutas))

    def _agregar_imagenes(self, rutas: list[str]) -> None:
        validas = filtrar_imagenes(rutas)
        if not validas:
            QMessageBox.information(
                self, "Nada para agregar",
                "Ninguno de los archivos es una imagen que pueda leer.\n\n"
                "Formatos admitidos: PNG, JPG, BMP y TIFF.")
            return
        nuevas = self.doc.agregar_varias(validas, temporal=False,
                                         origen=ORIGEN_IMAGEN)
        if nuevas:
            self._seleccionada = nuevas[-1].id
        self._refrescar()
        self._ir_a_la_ultima()

    def _ir_a_la_ultima(self) -> None:
        barra = self.scroll.verticalScrollBar()
        if barra is not None:
            barra.setValue(barra.maximum())

    # ── Arrastrar y soltar ────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() and filtrar_imagenes(
                u.toLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        rutas = [u.toLocalFile() for u in event.mimeData().urls()]
        validas = filtrar_imagenes(rutas)
        if validas:
            self._agregar_imagenes(sorted(validas))
            event.acceptProposedAction()

    # ── Guardado ──────────────────────────────────────────────────────────────

    def _guardar(self) -> None:
        if self.doc.vacio or self._guardando:
            return

        faltantes = self.doc.faltantes()
        if faltantes:
            QMessageBox.warning(
                self, "Faltan imágenes",
                f"{len(faltantes)} página(s) apuntan a archivos que ya no "
                "están en el disco.\n\nQuitalas de la lista y volvé a "
                "escanearlas antes de guardar.")
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
            self._seleccionada = None
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

    def _on_apilado(self, apilado: bool) -> None:
        """En ventanas angostas la vista previa estorba: las miniaturas de
        la lista ya alcanzan para saber qué página es cuál."""
        self.panel_previa.setVisible(not apilado and not self.doc.vacio)

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # La vista previa se escala al panel, así que hay que redibujarla.
        self._refrescar_previa()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._on_volver()
            return
        if (event.key() == Qt.Key.Key_N
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._escanear()
            return
        if (event.key() == Qt.Key.Key_S
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._guardar()
            return
        if self._seleccionada is not None and \
                event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Up:
                self._mover(self._seleccionada, -1)
                return
            if event.key() == Qt.Key.Key_Down:
                self._mover(self._seleccionada, 1)
                return
        super().keyPressEvent(event)

    def limpiar_temporales(self) -> None:
        """Borra los escaneos temporales que esta herramienta creó.

        Se llama al cerrar la app o al salir de la herramienta. Las
        imágenes que el usuario importó desde su disco no se tocan.
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
