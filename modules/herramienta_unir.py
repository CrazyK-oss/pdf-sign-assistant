"""
modules/herramienta_unir.py
============================================================
Herramienta "Unir y dividir PDFs".

Las dos operaciones que uno termina buscando en una página web cualquiera
—pegar varios PDF en uno, o separar uno en varios— con la ventaja de que
acá los archivos no salen de la máquina.

Por qué es una pantalla aparte de "Escanear a PDF"
--------------------------------------------------
Por debajo son lo mismo: una lista ordenada de páginas que termina en un
PDF, y de hecho comparten el modelo (documento.py), el motor de escritura
(armado_pdf.py) y la lista con su vista previa (lista_paginas.py).

Lo que cambia es de dónde vienen las páginas y qué se hace al final. Acá
no hay escáner ni calidad de compresión que elegir —las páginas se copian
tal cual y no se recomprime nada— y en cambio hay una operación que allá
no tiene sentido: partir el resultado en varios archivos.

Meter las dos cosas en una sola pantalla habría dejado la mitad de los
controles apagados según de dónde hubiera salido la primera página.

Lo que NO hace
--------------
No rasteriza. Una página que entra como PDF sale como PDF, con su texto
seleccionable. Sólo se convierten las imágenes que se agreguen a mano.
"""

from __future__ import annotations

import logging
import os
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from modules.armado_pdf import (
    ErrorArmado,
    abrir_en,
    armar_pdf,
    armar_varios,
    instantanea,
)
from modules.documento import (
    ORIGEN_IMAGEN,
    Documento,
    con_extension_pdf,
    es_pdf,
    filtrar_soportados,
    formatear_rangos,
    parsear_grupos,
)
from modules.imagen_pdf import CALIDAD_DEFECTO, formatear_peso
from modules.lista_paginas import PanelPaginas
from modules.previa import limpiar_cache
from modules.theme import SIZE, SPACE, repolish, theme_signals
from modules.ui import (
    Aviso,
    BarraInferior,
    BarraSuperior,
    Chip,
    boton,
    boton_icono,
    etiqueta,
    icono_label,
    separador_v,
)

log = logging.getLogger(__name__)

FILTRO_ENTRADA = ("Documentos e imágenes (*.pdf *.png *.jpg *.jpeg *.bmp "
                  "*.tif *.tiff);;Documentos PDF (*.pdf)")


# ═══════════════════════════════════════════════════════════════════════════════
#  Workers
# ═══════════════════════════════════════════════════════════════════════════════

class _WorkerUnir(QThread):
    """Escribe el PDF unido en segundo plano."""

    progreso = pyqtSignal(int, str)
    listo    = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, paginas, destino: Path):
        super().__init__()              # SIN parent= a propósito
        self._paginas = instantanea(paginas)
        self._destino = Path(destino)

    def run(self):
        try:
            armar_pdf(self._paginas, self._destino, cal=CALIDAD_DEFECTO,
                      progreso=self.progreso.emit)
            self.listo.emit(str(self._destino))
        except Exception as e:                           # noqa: BLE001
            tb = traceback.format_exc()
            log.error("Error al unir el PDF:\n%s", tb)
            self.error.emit(f"{e}\n\n─── Traceback completo ───\n{tb}")


class _WorkerDividir(QThread):
    """Escribe los trozos en segundo plano."""

    progreso = pyqtSignal(int, str)
    listo    = pyqtSignal(list)         # rutas escritas
    error    = pyqtSignal(str)

    def __init__(self, trabajos):
        super().__init__()
        self._trabajos = [(instantanea(paginas), Path(destino))
                          for paginas, destino in trabajos]

    def run(self):
        try:
            hechos = armar_varios(self._trabajos, cal=CALIDAD_DEFECTO,
                                  progreso=self.progreso.emit)
            self.listo.emit([str(r) for r in hechos])
        except Exception as e:                           # noqa: BLE001
            tb = traceback.format_exc()
            log.error("Error al dividir el PDF:\n%s", tb)
            self.error.emit(f"{e}\n\n─── Traceback completo ───\n{tb}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Diálogo de división
# ═══════════════════════════════════════════════════════════════════════════════

class DialogoDividir(QDialog):
    """Pregunta CÓMO partir el documento.

    Tres formas, porque son tres necesidades distintas:

      una por página   separar un lote escaneado de comprobantes
      cada N páginas   un legajo con fichas de tamaño fijo
      por rangos       "los capítulos van 1-10, 11-24 y 25-40"

    La validación de los rangos es en vivo: el mensaje de error de
    `parsear_grupos` está escrito para mostrarse tal cual, así que el
    diálogo lo pone abajo y desactiva el botón hasta que se entienda.
    """

    #: Modos, para que la vista no compare cadenas sueltas.
    UNA, CADA, RANGOS = "una", "cada", "rangos"

    def __init__(self, total: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dividir el documento")
        self.setObjectName("pantalla")
        self.setMinimumWidth(460)
        self._total = total
        self._grupos: list[list[int]] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        lay.setSpacing(SPACE["md"])

        lay.addWidget(etiqueta(f"El documento tiene {total} páginas. "
                               "¿Cómo querés separarlo?", rol="cuerpo",
                               wrap=True))

        self.grupo = QButtonGroup(self)
        self.rb_una = QRadioButton("Una parte por página")
        self.rb_cada = QRadioButton("Cada")
        self.rb_rangos = QRadioButton("Por rangos:")
        for i, rb in enumerate((self.rb_una, self.rb_cada, self.rb_rangos)):
            self.grupo.addButton(rb, i)
            rb.toggled.connect(self._revalidar)

        lay.addWidget(self.rb_una)

        fila = QHBoxLayout()
        fila.setSpacing(SPACE["sm"])
        fila.addWidget(self.rb_cada)
        self.spin = QSpinBox()
        self.spin.setRange(1, max(1, total))
        self.spin.setValue(min(2, max(1, total)))
        self.spin.setFixedWidth(80)
        self.spin.valueChanged.connect(self._revalidar)
        fila.addWidget(self.spin)
        fila.addWidget(etiqueta("páginas", rol="cuerpo"))
        fila.addStretch(1)
        lay.addLayout(fila)

        lay.addWidget(self.rb_rangos)
        # QLineEdit pelado y no Buscador: ese dibuja una lupa adentro, y
        # acá no se busca nada, se escribe.
        self.campo = QLineEdit()
        self.campo.setPlaceholderText("por ejemplo:  1-10, 11-24, 25-40")
        self.campo.textChanged.connect(self._revalidar)
        lay.addWidget(self.campo)

        self.aviso = Aviso("", tono="warn")
        self.aviso.hide()
        lay.addWidget(self.aviso)

        self.resumen = etiqueta("", rol="hint", wrap=True)
        lay.addWidget(self.resumen)

        self.botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setText("Dividir")
        cancelar = self.botones.button(QDialogButtonBox.StandardButton.Cancel)
        cancelar.setText("Cancelar")
        # Sin esto los dos salen con el relleno de acción principal y el
        # diálogo no dice cuál es cuál.
        cancelar.setProperty("variant", "secondary")
        repolish(cancelar)
        self.botones.accepted.connect(self.accept)
        self.botones.rejected.connect(self.reject)
        lay.addWidget(self.botones)

        self.rb_una.setChecked(True)
        self._revalidar()

    # ── Validación ────────────────────────────────────────────────────────────

    @property
    def modo(self) -> str:
        if self.rb_cada.isChecked():
            return self.CADA
        if self.rb_rangos.isChecked():
            return self.RANGOS
        return self.UNA

    def grupos(self) -> list[list[int]]:
        """Las posiciones (0-based) de cada archivo resultante."""
        if self.modo == self.UNA:
            return [[i] for i in range(self._total)]
        if self.modo == self.CADA:
            n = self.spin.value()
            return [list(range(i, min(i + n, self._total)))
                    for i in range(0, self._total, n)]
        return list(self._grupos)

    def _revalidar(self) -> None:
        rangos = self.modo == self.RANGOS
        self.campo.setEnabled(rangos)
        self.spin.setEnabled(self.modo == self.CADA)

        error = ""
        if rangos:
            try:
                self._grupos = parsear_grupos(self.campo.text(), self._total)
            except ValueError as e:
                self._grupos = []
                error = str(e)

        # El borde rojo del campo lo pone el tema con [invalid="true"]:
        # el aviso de abajo dice qué pasa, el borde dice dónde.
        self.campo.setProperty("invalid", "true" if error else "false")
        repolish(self.campo)

        if error:
            self.aviso.mostrar(error, "warn")
            self.resumen.setText("")
        else:
            self.aviso.hide()
            self.resumen.setText(self._describir())

        self.botones.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            not error and bool(self.grupos()))

    def _describir(self) -> str:
        grupos = self.grupos()
        if not grupos:
            return ""
        cabeza = ";  ".join(formatear_rangos(g) for g in grupos[:4])
        if len(grupos) > 4:
            cabeza += ";  …"
        plural = "archivos" if len(grupos) != 1 else "archivo"
        return f"Van a salir {len(grupos)} {plural}:  {cabeza}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Estado vacío
# ═══════════════════════════════════════════════════════════════════════════════

class PanelVacioUnir(QFrame):
    """Lo primero que se ve."""

    agregar_pedido = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panelVacio")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE["xl"], SPACE["3xl"], SPACE["xl"], SPACE["3xl"])
        lay.setSpacing(SPACE["md"])
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lay.addWidget(icono_label("unir", 52, color="primary"), 0,
                      Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(SPACE["sm"])
        lay.addWidget(etiqueta("Agregá los PDF que querés combinar", rol="titulo",
                               align=Qt.AlignmentFlag.AlignCenter))
        lay.addWidget(etiqueta(
            "Sus páginas aparecen acá, todas juntas y en orden. Podés moverlas,\n"
            "girarlas o quitar las que sobren, y después guardar un PDF nuevo\n"
            "o separarlo en varios archivos.",
            rol="cuerpo", wrap=True, align=Qt.AlignmentFlag.AlignCenter))
        lay.addSpacing(SPACE["md"])

        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addWidget(boton("Agregar archivos…", icono="documento-mas",
                             height=SIZE["btn_lg"], min_w=210,
                             on_click=self.agregar_pedido.emit))
        fila.addStretch(1)
        lay.addLayout(fila)

        lay.addSpacing(SPACE["sm"])
        lay.addWidget(etiqueta("…o arrastralos a esta ventana", rol="hint",
                               align=Qt.AlignmentFlag.AlignCenter))
        lay.addSpacing(SPACE["md"])
        lay.addWidget(etiqueta(
            "Los archivos no salen de tu computadora, y el texto de los PDF "
            "se conserva: las páginas se copian, no se convierten en imagen.",
            rol="hint", wrap=True, align=Qt.AlignmentFlag.AlignCenter))


# ═══════════════════════════════════════════════════════════════════════════════
#  Vista principal
# ═══════════════════════════════════════════════════════════════════════════════

class VistaUnirDividirPdf(QWidget):
    """
    Señales:
      volver()                → el usuario pidió salir al menú
      documento_guardado(str) → se escribió un PDF (ruta absoluta)
    """

    volver = pyqtSignal()
    documento_guardado = pyqtSignal(str)

    def __init__(self, carpeta_destino: Path, parent=None):
        super().__init__(parent)
        self.setObjectName("pantalla")
        self.setAcceptDrops(True)

        self.carpeta_destino = Path(carpeta_destino)
        self.doc = Documento()
        self._worker: QThread | None = None

        self._construir_ui()
        self._refrescar()
        theme_signals.changed.connect(self._on_tema_cambiado)

    # ── Construcción ──────────────────────────────────────────────────────────

    def _construir_ui(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        self.cabecera = BarraSuperior("Unir y dividir PDFs", icono_nombre="unir")
        self.cabecera.agregar(boton("Volver al menú", variant="ghost",
                                    icono="chevron-izq",
                                    tooltip="Volver al menú de herramientas (Esc)",
                                    on_click=self._on_volver))
        raiz.addWidget(self.cabecera)
        raiz.addWidget(self._barra_acciones())

        self.panel_vacio = PanelVacioUnir()
        self.panel_vacio.agregar_pedido.connect(self._agregar_dialogo)

        self.panel = PanelPaginas(self.doc, self.panel_vacio)
        self.panel.cambiado.connect(self._refrescar)
        raiz.addWidget(self.panel, 1)

        self.pie = BarraInferior("")
        self.chip_paginas = Chip("Sin páginas", tono="neutro",
                                 icono_nombre="documentos")
        self.pie.agregar(self.chip_paginas)

        self.barra_progreso = QProgressBar()
        self.barra_progreso.setFixedWidth(180)
        self.barra_progreso.setTextVisible(False)
        self.barra_progreso.hide()
        self.pie.agregar(self.barra_progreso)

        # Ctrl+Shift+D y no Ctrl+D: ese último ya es el cambio de tema, y
        # está registrado como QShortcut en la ventana, así que se lo
        # quedaría antes de que este keyPressEvent llegara a verlo.
        self.btn_dividir = boton("Dividir…", icono="tijera", variant="secondary",
                                 height=SIZE["btn_lg"], enabled=False,
                                 tooltip="Separar el documento en varios "
                                         "archivos (Ctrl+Shift+D)",
                                 on_click=self._dividir)
        self.pie.agregar(self.btn_dividir)

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

        self.btn_agregar = boton(
            "Agregar archivos…", icono="documento-mas", min_w=190,
            tooltip="Sumar las páginas de otro PDF o de una imagen (Ctrl+O)",
            on_click=self._agregar_dialogo)
        lay.addWidget(self.btn_agregar)

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

        self.chip_archivos = Chip("", tono="neutro", icono_nombre="documento")
        lay.addWidget(self.chip_archivos)
        return marco

    # ── Estado ────────────────────────────────────────────────────────────────

    @property
    def _ocupado(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _refrescar(self) -> None:
        self.panel.refrescar()

        vacio = self.doc.vacio
        ocupado = self._ocupado
        self.panel.set_habilitado(not ocupado)

        self.btn_guardar.setEnabled(not vacio and not ocupado)
        self.btn_dividir.setEnabled(self.doc.total > 1 and not ocupado)
        self.btn_agregar.setEnabled(not ocupado)
        for b in (self.btn_invertir, self.btn_rotar_todas, self.btn_vaciar):
            b.setEnabled(not vacio and not ocupado)

        self.chip_paginas.set_estado(
            self.doc.descripcion(), "primary" if not vacio else "neutro",
            "documentos")

        archivos = len(self.doc.archivos_pdf())
        if archivos:
            self.chip_archivos.set_estado(
                f"{archivos} PDF de origen" if archivos != 1 else "1 PDF de origen",
                "neutro", "documento")
            self.chip_archivos.show()
        else:
            self.chip_archivos.hide()

        faltantes = self.doc.faltantes()
        if faltantes:
            self.pie.set_estado(
                f"{len(faltantes)} archivo(s) ya no están en el disco: "
                "quitá esas páginas antes de guardar.", rol="error", tono="err")
        elif vacio:
            self.pie.set_estado("Agregá un PDF para empezar.")
        elif self.doc.total == 1:
            self.pie.set_estado("Agregá otro archivo para unirlo, o guardá "
                                "esta página sola.")
        else:
            partes = []
            giradas = self.doc.resumen_rotaciones()
            if giradas:
                partes.append(giradas)
            partes.append("Reordená lo que haga falta y guardá, o dividí el "
                          "documento en varios archivos.")
            self.pie.set_estado(".  ".join(partes))

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
            self, "Vaciar la lista",
            f"¿Quitar las {self.doc.total} páginas y empezar de nuevo?\n\n"
            "Tus archivos originales no se tocan.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if respuesta == QMessageBox.StandardButton.Yes:
            self.doc.limpiar()
            self.panel.marcar(None)
            limpiar_cache()
            self._refrescar()

    # ── Entrada de archivos ───────────────────────────────────────────────────

    def _agregar_dialogo(self) -> None:
        rutas, _ = QFileDialog.getOpenFileNames(
            self, "Agregar PDF o imágenes", os.path.expanduser("~"),
            FILTRO_ENTRADA)
        if rutas:
            self._agregar(rutas)

    def _agregar(self, rutas: list[str]) -> None:
        """Suma los archivos al final, en el orden en que llegaron."""
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
                ultima = self.doc.agregar(ruta, temporal=False,
                                          origen=ORIGEN_IMAGEN).id

        if ultima is not None:
            self.panel.marcar(ultima)
        self._refrescar()
        self.panel.ir_a_la_ultima()

        if problemas:
            QMessageBox.warning(self, "No se pudieron abrir todos los archivos",
                                "\n\n".join(problemas))

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() and filtrar_soportados(
                u.toLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        validas = filtrar_soportados(u.toLocalFile()
                                     for u in event.mimeData().urls())
        if validas:
            self._agregar(sorted(validas))
            event.acceptProposedAction()

    # ── Guardar (unir) ────────────────────────────────────────────────────────

    def _falta_algo(self) -> bool:
        faltantes = self.doc.faltantes()
        if not faltantes:
            return False
        QMessageBox.warning(
            self, "Faltan archivos",
            f"{len(faltantes)} página(s) apuntan a archivos que ya no están "
            "en el disco.\n\nQuitalas de la lista antes de guardar.")
        return True

    def _guardar(self) -> None:
        if self.doc.vacio or self._ocupado or self._falta_algo():
            return

        self.carpeta_destino.mkdir(parents=True, exist_ok=True)
        sugerido = self.carpeta_destino / self.doc.nombre_sugerido()
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar el PDF unido", str(sugerido),
            "Documentos PDF (*.pdf)")
        if not ruta:
            return

        destino = Path(ruta).parent / con_extension_pdf(Path(ruta).name)
        self._lanzar(_WorkerUnir(list(self.doc.paginas), destino),
                     self._on_unido)

    # ── Dividir ───────────────────────────────────────────────────────────────

    def _dividir(self) -> None:
        if self.doc.total < 2 or self._ocupado or self._falta_algo():
            return

        dlg = DialogoDividir(self.doc.total, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        trozos = self.doc.partir_en(dlg.grupos())
        if not trozos:
            return

        carpeta = QFileDialog.getExistingDirectory(
            self, f"¿Dónde guardo los {len(trozos)} archivos?",
            str(self.carpeta_destino))
        if not carpeta:
            return

        carpeta = Path(carpeta)
        trabajos = [(list(t.paginas),
                     carpeta / t.nombre_de_trozo(i, len(trozos)))
                    for i, t in enumerate(trozos, 1)]

        existentes = [d.name for _, d in trabajos if d.exists()]
        if existentes and not self._confirmar_sobrescritura(existentes):
            return

        self._lanzar(_WorkerDividir(trabajos), self._on_dividido)

    def _confirmar_sobrescritura(self, nombres: list[str]) -> bool:
        """Dividir escribe varios archivos de una sola vez, sin pasar por el
        diálogo de guardar de Windows: si no se pregunta acá, nadie
        pregunta."""
        muestra = "\n".join(f"  · {n}" for n in nombres[:6])
        if len(nombres) > 6:
            muestra += f"\n  … y {len(nombres) - 6} más"
        respuesta = QMessageBox.question(
            self, "Ya existen archivos con ese nombre",
            f"En esa carpeta ya hay {len(nombres)} archivo(s) que se van a "
            f"reemplazar:\n\n{muestra}\n\n¿Los sobrescribo?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return respuesta == QMessageBox.StandardButton.Yes

    # ── Ejecución en segundo plano ────────────────────────────────────────────

    def _lanzar(self, worker: QThread, al_terminar) -> None:
        self.barra_progreso.setValue(0)
        self.barra_progreso.show()
        self._worker = worker
        worker.progreso.connect(self._on_progreso)     # type: ignore[attr-defined]
        worker.listo.connect(al_terminar)              # type: ignore[attr-defined]
        worker.error.connect(self._on_error)           # type: ignore[attr-defined]
        worker.finished.connect(self._on_worker_termino)
        worker.start()
        self._refrescar()

    def _on_progreso(self, porcentaje: int, etapa: str) -> None:
        self.barra_progreso.setValue(porcentaje)
        self.pie.set_estado(etapa, tono="info")

    def _on_unido(self, ruta: str) -> None:
        self.barra_progreso.hide()
        destino = Path(ruta)
        try:
            peso = destino.stat().st_size
        except OSError:
            peso = 0
        self.pie.set_estado(
            f"Guardado: {destino.name}  ·  {formatear_peso(peso)}",
            rol="ok", tono="ok")
        self.documento_guardado.emit(ruta)
        QMessageBox.information(
            self, "PDF guardado",
            f"Se guardó «{destino.name}» ({formatear_peso(peso)}) con "
            f"{self.doc.total} página(s).")
        self._refrescar()

    def _on_dividido(self, rutas: list) -> None:
        self.barra_progreso.hide()
        self.pie.set_estado(f"Se guardaron {len(rutas)} archivos.",
                            rol="ok", tono="ok")
        for r in rutas:
            self.documento_guardado.emit(str(r))

        carpeta = Path(rutas[0]).parent if rutas else self.carpeta_destino
        nombres = "\n".join(f"  · {Path(r).name}" for r in rutas[:8])
        if len(rutas) > 8:
            nombres += f"\n  … y {len(rutas) - 8} más"
        QMessageBox.information(
            self, "Documento dividido",
            f"Se guardaron {len(rutas)} archivos en:\n{carpeta}\n\n{nombres}")
        self._refrescar()

    def _on_error(self, mensaje: str) -> None:
        self.barra_progreso.hide()
        log.error("Fallo al escribir: %s", mensaje)
        cuadro = QMessageBox(self)
        cuadro.setIcon(QMessageBox.Icon.Warning)
        cuadro.setWindowTitle("No se pudo guardar")
        cuadro.setText(mensaje.split("\n\n")[0])
        cuadro.setDetailedText(mensaje)
        cuadro.exec()
        self.pie.set_estado("No se pudo guardar.", rol="error", tono="err")

    def _on_worker_termino(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self._refrescar()

    # ── Eventos ───────────────────────────────────────────────────────────────

    def _on_tema_cambiado(self, _modo: str) -> None:
        self._refrescar()

    def _on_volver(self) -> None:
        if self._ocupado:
            QMessageBox.information(self, "Guardado en curso",
                                    "Esperá a que termine de escribirse.")
            return
        if not self.doc.vacio:
            respuesta = QMessageBox.question(
                self, "Salir de la herramienta",
                f"Tenés {self.doc.total} página(s) sin guardar.\n\n"
                "Si salís ahora se descarta la lista (tus archivos "
                "originales no se tocan). ¿Salir igual?",
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
        if ctrl and event.key() == Qt.Key.Key_O:
            self._agregar_dialogo()
            return
        if ctrl and event.key() == Qt.Key.Key_S:
            self._guardar()
            return
        if (ctrl and event.key() == Qt.Key.Key_D
                and event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._dividir()
            return
        if ctrl and self.panel.seleccionada is not None:
            if event.key() == Qt.Key.Key_Up:
                self.panel.mover(self.panel.seleccionada, -1)
                return
            if event.key() == Qt.Key.Key_Down:
                self.panel.mover(self.panel.seleccionada, 1)
                return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        try:
            theme_signals.changed.disconnect(self._on_tema_cambiado)
        except (TypeError, RuntimeError):
            pass
        limpiar_cache()
        super().closeEvent(event)
