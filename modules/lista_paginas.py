"""
modules/lista_paginas.py
============================================================
La lista de páginas con su vista previa: el corazón de las dos
herramientas que arman PDFs.

"Escanear a PDF" y "Unir y dividir PDFs" se sienten distintas —una mira al
escáner, la otra a los archivos— pero lo que pasa en el medio de la
pantalla es idéntico: una lista de páginas con miniatura, que se reordena,
se gira y se recorta, y un panel al lado que muestra la seleccionada en
grande. Duplicar eso serían unas cuatrocientas líneas repetidas y, peor,
dos comportamientos que se van separando de a poco con cada arreglo.

Así que vive acá y las dos pantallas lo embeben.

Quién manda sobre el modelo
---------------------------
`PanelPaginas` recibe el `Documento` y aplica él mismo las operaciones de
la lista (mover, girar, quitar), avisando con `cambiado`. La alternativa
—emitir "el usuario pidió subir la página 7" y que cada herramienta lo
aplique— duplicaría en las dos pantallas la parte más fácil de equivocar:
mantener la selección al reordenar y no perderla al borrar.

Lo que sí queda afuera son las decisiones de cada herramienta: de dónde
salen las páginas nuevas, qué dice el pie, cuándo se puede guardar.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from modules.documento import Documento, Pagina
from modules.imagen_pdf import formatear_peso
from modules.previa import LADO_MINIATURA, dimensiones, escalar_para
from modules.theme import BREAKPOINT, SIZE, SPACE, repolish
from modules.ui import (
    AreaScroll,
    Aviso,
    FilaAdaptable,
    boton_icono,
    etiqueta,
    icono_label,
    separador_v,
    tarjeta,
)

#: Icono con el que se ilustra cada origen en la fila.
_ICONO_ORIGEN = {"escaner": "escaner", "imagen": "imagen", "pdf": "documento"}


# ═══════════════════════════════════════════════════════════════════════════════
#  Fila de una página
# ═══════════════════════════════════════════════════════════════════════════════

class FilaPagina(QFrame):
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
            self.setToolTip(str(pagina.ruta))
            return

        pm = escalar_para(self.lbl_thumb, pagina, tope=LADO_MINIATURA * 4)
        if pm.isNull():
            self.lbl_thumb.clear()
        else:
            self.lbl_thumb.setPixmap(pm)

        self.lbl_titulo.setText(f"Página {numero}")
        self.lbl_detalle.setText("  ·  ".join(_detalle(pagina)))
        self.lbl_detalle.setProperty("rol", "hint")
        repolish(self.lbl_detalle)
        self.setToolTip(f"{pagina.descripcion()}\n{pagina.ruta}")

    def mousePressEvent(self, event):
        self.seleccionada.emit(self.id_pagina)
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        self.seleccionada.emit(self.id_pagina)
        super().focusInEvent(event)


def _detalle(pagina: Pagina) -> list[str]:
    """La línea chica de la fila: de dónde salió y cómo es.

    Para una página de PDF se nombra el archivo y la página dentro de él;
    el peso NO se muestra, porque el del archivo es el del documento
    entero y poner "4,2 MB" en cada una de sus 30 páginas sería mentir
    treinta veces.
    """
    partes = [pagina.etiqueta_origen()]

    if pagina.es_pdf:
        partes.append(f"{pagina.nombre} · pág. {pagina.indice + 1}")
        ancho, alto = dimensiones(pagina)
        if ancho and alto:
            partes.append(f"{ancho}×{alto} pt")
    else:
        ancho, alto = dimensiones(pagina)
        if ancho and alto:
            partes.append(f"{ancho}×{alto} px")
        try:
            partes.append(formatear_peso(pagina.ruta.stat().st_size))
        except OSError:
            pass

    if pagina.rotacion:
        partes.append(f"girada {pagina.rotacion}°")
    return partes


# ═══════════════════════════════════════════════════════════════════════════════
#  Lista + vista previa
# ═══════════════════════════════════════════════════════════════════════════════

class PanelPaginas(FilaAdaptable):
    """La lista de páginas y el panel de vista previa, lado a lado.

    Se apila en vertical —y esconde la previa— cuando la ventana se pone
    angosta: dos paneles de 200 px no le sirven a nadie.
    """

    #: El modelo cambió por una acción de la lista (mover, girar, quitar).
    cambiado = pyqtSignal()
    #: Cambió la página seleccionada.
    seleccion_cambiada = pyqtSignal(int)

    def __init__(self, doc: Documento, panel_vacio: QWidget, parent=None):
        super().__init__(breakpoint_px=BREAKPOINT["lg"], spacing=SPACE["lg"],
                         parent=parent)
        self.doc = doc
        self._filas: dict[int, FilaPagina] = {}
        self._seleccionada: int | None = None

        self.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        self.orientacion_cambiada.connect(self._on_apilado)

        self.pila = QStackedWidget()
        self.panel_vacio = panel_vacio
        self.scroll = AreaScroll(margenes=(0, 0, SPACE["sm"], 0),
                                 spacing=SPACE["sm"])
        self.lay_filas = self.scroll.lay
        self.lay_filas.addStretch(1)
        self.pila.addWidget(self.panel_vacio)   # índice 0
        self.pila.addWidget(self.scroll)        # índice 1
        self.agregar(self.pila, 3)

        self.panel_previa = self._construir_previa()
        self.agregar(self.panel_previa, 2)

    # ── Construcción ──────────────────────────────────────────────────────────

    def _construir_previa(self) -> QWidget:
        marco, lay = tarjeta(padding=SPACE["lg"], spacing=SPACE["md"])
        marco.setMinimumWidth(280)
        marco.setSizePolicy(QSizePolicy.Policy.Preferred,
                            QSizePolicy.Policy.Preferred)

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

    # ── Estado ────────────────────────────────────────────────────────────────

    @property
    def seleccionada(self) -> int | None:
        return self._seleccionada

    @property
    def pagina_activa(self) -> Pagina | None:
        return (self.doc.pagina(self._seleccionada)
                if self._seleccionada is not None else None)

    def set_habilitado(self, habilitado: bool) -> None:
        """Bloquea las acciones de las filas mientras se guarda o escanea."""
        for fila in self._filas.values():
            fila.setEnabled(habilitado)

    def refrescar(self) -> None:
        """Reconstruye la lista y la previa a partir del modelo."""
        self._sincronizar_filas()
        vacio = self.doc.vacio
        self.pila.setCurrentIndex(0 if vacio else 1)
        self.panel_previa.setVisible(not vacio and not self.apilado)
        self._refrescar_previa()

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
                fila = FilaPagina(pagina, indice + 1)
                fila.seleccionada.connect(self.seleccionar)
                fila.subir_pedido.connect(lambda i: self.mover(i, -1))
                fila.bajar_pedido.connect(lambda i: self.mover(i, 1))
                fila.rotar_pedido.connect(self.rotar)
                fila.quitar_pedido.connect(self.quitar)
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
        pagina = self.pagina_activa
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
            self.lbl_previa.setText("No se pudo mostrar esta página")
            self.aviso_previa.mostrar(
                "El archivo de esta página ya no está o no se puede leer. "
                "Quitala de la lista y volvé a agregarla.", "err")
        else:
            self.lbl_previa.setPixmap(pm)
            self.aviso_previa.setVisible(False)

        numero = self.doc.indice_de(pagina.id) + 1
        detalle = f"Página {numero} de {self.doc.total}"
        ancho, alto = dimensiones(pagina)
        if ancho and alto:
            detalle += f"  ·  {ancho}×{alto} {'pt' if pagina.es_pdf else 'px'}"
        if pagina.rotacion:
            detalle += f"  ·  girada {pagina.rotacion}°"
        self.lbl_previa_info.setText(detalle)

    # ── Acciones sobre el modelo ──────────────────────────────────────────────

    def seleccionar(self, id_pagina: int) -> None:
        if id_pagina == self._seleccionada:
            return
        self._seleccionada = id_pagina
        for pid, fila in self._filas.items():
            fila.setProperty("activa", "true" if pid == id_pagina else "false")
            repolish(fila)
        self._refrescar_previa()
        self.seleccion_cambiada.emit(id_pagina)

    def mover(self, id_pagina: int, desplazamiento: int) -> None:
        if self.doc.mover(id_pagina, desplazamiento):
            self._seleccionada = id_pagina
            self.refrescar()
            self.cambiado.emit()

    def rotar(self, id_pagina: int, grados: int) -> None:
        if self.doc.rotar(id_pagina, grados):
            self._seleccionada = id_pagina
            self.refrescar()
            self.cambiado.emit()

    def quitar(self, id_pagina: int) -> None:
        if self.doc.quitar(id_pagina) is None:
            return
        if self._seleccionada == id_pagina:
            self._seleccionada = None
        # El temporal se borra al cerrar, no ahora: si el usuario se
        # arrepiente, todavía puede volver a importarlo.
        self.refrescar()
        self.cambiado.emit()

    def marcar(self, id_pagina: int | None) -> None:
        """Fija la selección sin pasar por la comparación de `seleccionar`.

        Lo usan las herramientas después de agregar páginas, para dejar
        marcada la última.
        """
        self._seleccionada = id_pagina

    def ir_a_la_ultima(self) -> None:
        barra = self.scroll.verticalScrollBar()
        if barra is not None:
            barra.setValue(barra.maximum())

    # ── Navegación por teclado ────────────────────────────────────────────────

    def mover_seleccion(self, paso: int) -> bool:
        """Sube o baja la selección una página. False si no había a dónde."""
        if self.doc.vacio:
            return False
        actual = self.doc.indice_de(self._seleccionada or -1)
        destino = max(0, min(self.doc.total - 1,
                             (0 if actual < 0 else actual + paso)))
        if destino == actual:
            return False
        self.seleccionar(self.doc.paginas[destino].id)
        return True

    # ── Eventos ───────────────────────────────────────────────────────────────

    def _on_apilado(self, apilado: bool) -> None:
        self.panel_previa.setVisible(not apilado and not self.doc.vacio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # La previa se lee al tamaño real del panel: si la ventana cambió,
        # hay que volver a pedirla o queda escalada desde menos píxeles.
        self._refrescar_previa()
