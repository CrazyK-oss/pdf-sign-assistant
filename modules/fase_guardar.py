"""
modules/fase_guardar.py
=======================
Fase final del flujo: confirmación y guardado del PDF modificado.

Recibe un TrabajoFirma ya completo (todas las páginas elegidas con su
imagen) y produce el PDF final en pdfs_firmados/.

Emite:
  - guardado_listo(Path)  → ruta del PDF final
  - cancelado()           → el usuario volvió atrás

Multipágina
-----------
El worker reemplaza TODAS las páginas del trabajo en una sola pasada de
escritura, aplicando la rotación elegida en cada imagen. El progreso se
reparte entre las páginas, así que con 10 hojas la barra avanza de a
poco en vez de quedarse clavada.

Al guardar se escriben metadatos con las páginas firmadas (`/PSAPaginas`).
Eso permite que, al reabrir el documento más tarde para enviarlo por
correo, el resumen diga las páginas reales en vez del "página 1" fijo
que se mostraba antes.

Correcciones que sostiene esta versión
--------------------------------------
* img2pdf corre en un SUBPROCESO aislado: puede crashear a nivel de
  extensión C (pikepdf/libjpeg), y ahí ningún try/except de Python
  llega a atrapar nada.
* Ese subproceso NO se lanza en modo congelado: `sys.executable` dentro
  de un .exe de PyInstaller es la propia app, así que "convertir la
  imagen" abría una segunda instancia del programa.
* La emisión de guardado_listo se difiere con QueuedConnection.
* logging.basicConfig() no se llama al importar.
"""

from __future__ import annotations

import logging
import os
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from modules.imagen_pdf import (
    CALIDAD_DEFECTO,
    LIMITE_CORREO_MB,
    _borrar_si_existe,
    _convertir_imagen_a_pdf,
    calidad,
    excede_limite,
    formatear_peso,
    opciones_calidad,
    siguiente_mas_liviana,
)
from modules.theme import SIZE, SPACE, repolish, theme_signals
from modules.trabajo import TrabajoFirma, formatear_paginas
from modules.ui import (
    AreaScroll,
    BarraInferior,
    BarraSuperior,
    boton,
    etiqueta,
    selector,
    tarjeta,
)

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

CARACTERES_INVALIDOS = set('/\\:*?"<>|')

# Clave propia en el diccionario Info del PDF con las páginas firmadas
CLAVE_META_PAGINAS = "/PSAPaginas"


# ─────────────────────────────────────────────────────────────────────────
#  Worker: arma el PDF final en hilo secundario
# ─────────────────────────────────────────────────────────────────────────
class _WorkerGuardar(QThread):
    progreso = pyqtSignal(int, str)   # (porcentaje 0-100, etiqueta)
    listo    = pyqtSignal(str)        # ruta del PDF final
    error    = pyqtSignal(str)        # mensaje de error completo

    def __init__(self, trabajo: TrabajoFirma, destino: Path,
                 cal=CALIDAD_DEFECTO):
        super().__init__()            # SIN parent= a propósito
        self._trabajo = trabajo
        self._destino = destino
        self._calidad = calidad(cal)

    def run(self):
        paginas = list(self._trabajo.paginas)
        log.debug("Worker iniciado — pdf=%s paginas=%s destino=%s",
                  self._trabajo.ruta_pdf, paginas, self._destino)
        temporales: list[str] = []
        try:
            if not self._trabajo.ruta_pdf.exists():
                raise FileNotFoundError(
                    f"El PDF de trabajo no existe: {self._trabajo.ruta_pdf}")
            if not paginas:
                raise ValueError("No hay páginas seleccionadas.")

            faltantes = self._trabajo.paginas_pendientes()
            if faltantes:
                raise ValueError(
                    "Faltan imágenes para las páginas "
                    f"{formatear_paginas(faltantes)}.")

            # ── 1: cada imagen → PDF de una página ──────────────────────
            paginas_pdf: dict[int, str] = {}
            total = len(paginas)
            for i, pagina in enumerate(paginas):
                ruta_img = self._trabajo.imagenes[pagina]
                if not Path(ruta_img).exists():
                    raise FileNotFoundError(
                        f"No se encuentra la imagen de la página {pagina + 1}:\n"
                        f"{ruta_img}")

                pct = 5 + int(i / total * 55)
                self.progreso.emit(
                    pct, f"Convirtiendo la página {pagina + 1} "
                         f"({i + 1} de {total})…")
                ruta_pdf_pag = _convertir_imagen_a_pdf(
                    ruta_img, self._trabajo.rotacion(pagina), self._calidad)
                paginas_pdf[pagina] = ruta_pdf_pag
                temporales.append(ruta_pdf_pag)

            # ── 2: abrir el PDF original ────────────────────────────────
            self.progreso.emit(62, "Leyendo el documento original…")
            try:
                from pypdf import PdfReader, PdfWriter
            except ImportError:
                from PyPDF2 import PdfReader, PdfWriter  # type: ignore

            lector_orig = PdfReader(str(self._trabajo.ruta_pdf))
            total_pags = len(lector_orig.pages)

            fuera = [p for p in paginas if p >= total_pags]
            if fuera:
                raise IndexError(
                    f"El documento tiene {total_pags} página(s); se pidió "
                    f"reemplazar {formatear_paginas(fuera)}.")

            # Los lectores de las páginas nuevas deben seguir vivos hasta
            # escribir: pypdf resuelve los objetos de forma perezosa.
            lectores_nuevos = {p: PdfReader(r) for p, r in paginas_pdf.items()}

            # ── 3: reemplazar todas las páginas elegidas ────────────────
            self.progreso.emit(72, f"Reemplazando {total} página(s)…")
            writer = PdfWriter()
            reemplazadas = 0
            for i, pag in enumerate(lector_orig.pages):
                if i in lectores_nuevos:
                    pag_nueva = lectores_nuevos[i].pages[0]
                    pag_nueva.mediabox = pag.mediabox
                    writer.add_page(pag_nueva)
                    reemplazadas += 1
                else:
                    writer.add_page(pag)

            # ── 4: metadatos con las páginas firmadas ───────────────────
            self.progreso.emit(85, "Escribiendo metadatos…")
            try:
                meta = dict(lector_orig.metadata or {})
                meta.update({
                    "/Producer": "PDF Sign Assistant",
                    CLAVE_META_PAGINAS: ",".join(str(p) for p in paginas),
                })
                writer.add_metadata(meta)
            except Exception as e:                   # noqa: BLE001
                # Un Info dict raro no debe impedir guardar el documento
                log.warning("No se pudieron escribir los metadatos: %s", e)

            # ── 5: escribir el resultado ────────────────────────────────
            self.progreso.emit(92, "Escribiendo el archivo final…")
            self._destino.parent.mkdir(parents=True, exist_ok=True)
            with open(self._destino, "wb") as f_out:
                writer.write(f_out)
            log.debug("Archivo escrito OK — %d páginas reemplazadas, %d bytes",
                      reemplazadas, self._destino.stat().st_size)

            self.progreso.emit(100, "¡Listo!")
            self.listo.emit(str(self._destino))

        except Exception as e:                       # noqa: BLE001
            tb = traceback.format_exc()
            log.error("Error en worker:\n%s", tb)
            self.error.emit(f"{e}\n\n─── Traceback completo ───\n{tb}")
        finally:
            for t in temporales:
                _borrar_si_existe(t)


def leer_paginas_firmadas(ruta_pdf: Path) -> list[int]:
    """Lee del PDF las páginas que firmó esta app.

    Devuelve [] si el documento no tiene el metadato (por ejemplo, si lo
    firmó una versión anterior).
    """
    try:
        from pypdf import PdfReader
        meta = PdfReader(str(ruta_pdf)).metadata or {}
        crudo = meta.get(CLAVE_META_PAGINAS)
        if not crudo:
            return []
        return sorted({
            int(x) for x in str(crudo).split(",")
            if x.strip().lstrip("-").isdigit()
        })
    except Exception:                                # noqa: BLE001
        return []


# ─────────────────────────────────────────────────────────────────────────
#  Pantalla de guardado
# ─────────────────────────────────────────────────────────────────────────
class FaseGuardar(QDialog):
    """
    Señales públicas:
      guardado_listo(object / Path)  → PDF guardado correctamente
      cancelado()                    → el usuario volvió atrás

    Señal interna (NO conectar desde fuera):
      _despachar_guardado_listo(str) → encolada con QueuedConnection para
          diferir la emisión de guardado_listo al siguiente ciclo del
          event loop.
    """

    guardado_listo = pyqtSignal(object)   # Path
    calidad_elegida = pyqtSignal(str)     # clave, para recordarla
    cancelado      = pyqtSignal()
    _despachar_guardado_listo = pyqtSignal(str)

    def __init__(self, trabajo: TrabajoFirma, carpeta_firmados: Path,
                 parent=None, calidad_inicial=CALIDAD_DEFECTO,
                 limite_mb: float = LIMITE_CORREO_MB):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window |
                            Qt.WindowType.WindowCloseButtonHint)
        self.setObjectName("pantalla")
        self.setMinimumSize(520, 460)

        self.trabajo = trabajo
        self._carpeta_firmados = carpeta_firmados
        self._calidad_inicial = calidad_inicial
        self._limite_mb = limite_mb
        self._worker: _WorkerGuardar | None = None
        self._ruta_final_pendiente: str | None = None

        # Conectar la señal interna ANTES de construir la UI.
        self._despachar_guardado_listo.connect(
            self._emitir_guardado_listo, Qt.ConnectionType.QueuedConnection)

        self._construir_ui()
        theme_signals.changed.connect(self._on_tema_cambiado)

    # ── UI ────────────────────────────────────────────────────────────
    def _construir_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        nombre_pdf = os.path.basename(str(self.trabajo.ruta_pdf))
        cantidad = self.trabajo.cantidad
        plural = "s" if cantidad != 1 else ""
        cab = BarraSuperior(
            f"Guardar  ·  {cantidad} página{plural} "
            f"({self.trabajo.etiqueta_paginas()})  ·  {nombre_pdf}")
        self.btn_volver = boton("←  Volver al escaneo", variant="ghost",
                                tooltip="Volver al paso anterior (Esc)",
                                on_click=self._on_cancelar)
        cab.agregar(self.btn_volver)
        raiz.addWidget(cab)

        cuerpo = AreaScroll(margenes=(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"]),
                            spacing=SPACE["md"])
        lay = cuerpo.lay
        lay.addWidget(self._panel_paginas())
        lay.addWidget(self._panel_nombre())
        lay.addWidget(self._panel_progreso())
        lay.addStretch()
        raiz.addWidget(cuerpo, 1)

        self.pie = BarraInferior("Revisá el nombre y confirmá para guardar.")
        self.btn_guardar = boton("Guardar documento", icono="check",
                                 variant="success", height=SIZE["btn_lg"],
                                 tooltip="Guardar el PDF firmado (Enter)",
                                 on_click=self._on_guardar)
        self.pie.agregar(self.btn_guardar)
        raiz.addWidget(self.pie)

        # La validación se conecta al final: durante la construcción el
        # setText() inicial dispararía el slot antes de que existan el
        # label de error y el botón que toca.
        self.input_nombre.textChanged.connect(self._validar_nombre)
        self._validar_nombre()

    def _panel_paginas(self) -> QFrame:
        """Resumen de qué imagen va en cada página."""
        panel, lay = tarjeta(acento=True, padding=SPACE["md"], spacing=SPACE["sm"])
        cantidad = self.trabajo.cantidad
        plural = "s" if cantidad != 1 else ""
        lay.addWidget(etiqueta(
            f"{cantidad} PÁGINA{plural.upper()} A REEMPLAZAR", rol="seccion"))

        for pagina in self.trabajo.paginas:
            ruta = self.trabajo.imagenes.get(pagina, "")
            rotacion = self.trabajo.rotacion(pagina)

            fila = QHBoxLayout()
            fila.setSpacing(SPACE["md"])

            thumb = QLabel()
            thumb.setObjectName("lienzoPagina")
            thumb.setFixedSize(52, 68)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pm = QPixmap(ruta)
            if not pm.isNull():
                if rotacion:
                    pm = pm.transformed(QTransform().rotate(rotacion),
                                        Qt.TransformationMode.SmoothTransformation)
                thumb.setPixmap(pm.scaled(
                    52, 68, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            fila.addWidget(thumb)

            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(etiqueta(f"Página {pagina + 1}", rol="subtitulo"))
            detalle = os.path.basename(ruta)
            if rotacion:
                detalle += f"  ·  rotada {rotacion}°"
            col.addWidget(etiqueta(detalle, rol="hint", wrap=True))
            col.addStretch()
            fila.addLayout(col, 1)

            contenedor = QFrame()
            contenedor.setLayout(fila)
            lay.addWidget(contenedor)

        return panel

    def _panel_nombre(self) -> QFrame:
        panel, lay = tarjeta(padding=SPACE["lg"], spacing=SPACE["sm"])
        lay.addWidget(etiqueta("Nombre del documento a guardar", rol="subtitulo"))
        lay.addWidget(etiqueta(
            f"Se guardará en:  {self._carpeta_firmados}", rol="hint", wrap=True))

        fila = QHBoxLayout()
        fila.setSpacing(SPACE["sm"])

        self.input_nombre = QLineEdit()
        self.input_nombre.setMinimumHeight(SIZE["input"])
        self.input_nombre.setPlaceholderText("ej: contrato_firmado")
        self.input_nombre.setClearButtonEnabled(True)
        self.input_nombre.returnPressed.connect(self._on_guardar)

        stem = Path(str(self.trabajo.ruta_pdf)).stem
        if stem.startswith("reedit_"):
            stem = stem[len("reedit_"):]
        self.input_nombre.setText(stem)
        self.input_nombre.selectAll()
        fila.addWidget(self.input_nombre, 1)
        fila.addWidget(etiqueta(".pdf", rol="hint"))
        lay.addLayout(fila)

        self.lbl_error_nombre = etiqueta("", rol="error", wrap=True)
        self.lbl_error_nombre.hide()
        lay.addWidget(self.lbl_error_nombre)

        lay.addSpacing(SPACE["sm"])
        fila_cal = QHBoxLayout()
        fila_cal.setSpacing(SPACE["sm"])
        fila_cal.addWidget(etiqueta("Calidad:", rol="hint"))
        opciones = opciones_calidad()
        self.combo_calidad = selector(
            [(c, n) for c, n, _ in opciones],
            actual=calidad(self._calidad_inicial).clave,
            tooltips={c: d for c, _, d in opciones},
            on_change=self._on_calidad, min_w=160)
        fila_cal.addWidget(self.combo_calidad)
        fila_cal.addStretch(1)
        lay.addLayout(fila_cal)

        self.lbl_calidad = etiqueta("", rol="hint", wrap=True)
        lay.addWidget(self.lbl_calidad)
        self._on_calidad(self.combo_calidad.currentData())
        return panel

    def _on_calidad(self, clave) -> None:
        """Explica la calidad elegida sin obligar a descubrir el tooltip."""
        cal = calidad(clave)
        self.lbl_calidad.setText(cal.descripcion)
        self.calidad_elegida.emit(cal.clave)

    def _panel_progreso(self) -> QFrame:
        self.panel_progreso, lay = tarjeta(padding=SPACE["md"], spacing=SPACE["sm"])
        self.lbl_progreso_etapa = etiqueta("Iniciando…", rol="ok")
        lay.addWidget(self.lbl_progreso_etapa)

        self.barra_progreso = QProgressBar()
        self.barra_progreso.setRange(0, 100)
        self.barra_progreso.setValue(0)
        self.barra_progreso.setTextVisible(False)
        lay.addWidget(self.barra_progreso)

        self.lbl_error_detalle = etiqueta("", rol="error", wrap=True)
        self.lbl_error_detalle.hide()
        lay.addWidget(self.lbl_error_detalle)

        self.panel_progreso.hide()
        return self.panel_progreso

    def _on_tema_cambiado(self, _modo: str):
        pass   # los estilos vienen del QSS; nada local que repintar

    # ── Validación ────────────────────────────────────────────────────
    def _validar_nombre(self, texto: str = "") -> str | None:
        """Devuelve el nombre normalizado, o None si es inválido.
        Muestra el error debajo del campo en tiempo real."""
        nombre = (texto or self.input_nombre.text()).strip()
        error = ""
        if not nombre:
            error = "El nombre no puede estar vacío."
        elif any(c in nombre for c in CARACTERES_INVALIDOS):
            error = 'El nombre no puede contener: / \\ : * ? " < > |'

        self.lbl_error_nombre.setText(error)
        self.lbl_error_nombre.setVisible(bool(error))
        self.input_nombre.setProperty("invalid", "true" if error else "false")
        repolish(self.input_nombre)
        self.btn_guardar.setEnabled(not error)

        if error:
            return None
        return nombre if nombre.lower().endswith(".pdf") else f"{nombre}.pdf"

    # ── Guardado ──────────────────────────────────────────────────────
    @pyqtSlot()
    def _on_guardar(self):
        if self._worker is not None and self._worker.isRunning():
            return

        nombre = self._validar_nombre()
        if nombre is None:
            self.input_nombre.setFocus()
            return

        if not self.trabajo.completo:
            QMessageBox.warning(
                self, "Faltan imágenes",
                "Todavía hay páginas sin imagen asignada:\n"
                f"{formatear_paginas(self.trabajo.paginas_pendientes())}")
            return

        destino = self._carpeta_firmados / nombre
        if destino.exists():
            resp = QMessageBox.question(
                self, "Archivo existente",
                f"Ya existe un archivo con ese nombre:\n{nombre}\n\n"
                "¿Querés reemplazarlo?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if resp != QMessageBox.StandardButton.Yes:
                return

        faltan_img = [p for p in self.trabajo.paginas
                      if not Path(self.trabajo.imagenes[p]).exists()]
        if faltan_img:
            QMessageBox.critical(
                self, "Archivos no encontrados",
                "No se encuentran las imágenes de las páginas "
                f"{formatear_paginas(faltan_img)}.\n\n"
                "Volvé al paso de escaneo y asignalas de nuevo.")
            return

        if not self.trabajo.ruta_pdf.exists():
            QMessageBox.critical(
                self, "Archivo no encontrado",
                f"No se encontró el PDF de trabajo:\n{self.trabajo.ruta_pdf}\n\n"
                "Cancelá y abrí el PDF nuevamente.")
            return

        self._ruta_final_pendiente = None
        self._set_guardando(True)

        self._worker = _WorkerGuardar(self.trabajo, destino,
                                      self.combo_calidad.currentData())
        self._worker.progreso.connect(self._on_progreso)
        self._worker.listo.connect(self._on_listo)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished_thread)
        self._worker.start()

    def _limpiar_worker(self):
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _set_guardando(self, guardando: bool):
        self.btn_guardar.setEnabled(not guardando)
        self.btn_volver.setEnabled(not guardando)
        self.input_nombre.setEnabled(not guardando)

        if guardando:
            self.btn_guardar.setText("Guardando…")
            self.pie.set_estado("Procesando, no cierres la ventana…", rol="ok")
            self.barra_progreso.setValue(0)
            self.lbl_progreso_etapa.setText("Iniciando…")
            self.lbl_progreso_etapa.setProperty("rol", "ok")
            repolish(self.lbl_progreso_etapa)
            self.lbl_error_detalle.hide()
            self.panel_progreso.show()
        else:
            self.btn_guardar.setText("Guardar documento")
            self.pie.set_estado("Revisá el nombre y confirmá para guardar.")

    @pyqtSlot(int, str)
    def _on_progreso(self, porcentaje: int, etapa: str):
        self.barra_progreso.setValue(porcentaje)
        self.lbl_progreso_etapa.setText(etapa)

    @pyqtSlot(str)
    def _on_listo(self, ruta_str: str):
        self._ruta_final_pendiente = ruta_str

    @pyqtSlot()
    def _on_finished_thread(self):
        """Slot de QThread.finished — corre en el hilo PRINCIPAL."""
        self._set_guardando(False)
        ruta = self._ruta_final_pendiente
        self._ruta_final_pendiente = None
        self._limpiar_worker()
        if ruta is None:
            return
        if not self._revisar_tamano(Path(ruta)):
            return          # el usuario eligió volver a guardar más liviano
        self._despachar_guardado_listo.emit(ruta)

    def _revisar_tamano(self, ruta: Path) -> bool:
        """Avisa si el PDF no va a entrar como adjunto y ofrece rehacerlo.

        Este documento existe para mandarse por correo: que pese más de lo
        que Outlook acepta lo vuelve inservible, y descubrirlo recién al
        adjuntarlo obliga a rehacer todo el trabajo.

        Devuelve False si se relanzó el guardado con otra calidad.
        """
        try:
            peso = ruta.stat().st_size
        except OSError:
            return True
        if not excede_limite(peso, self._limite_mb):
            return True

        mas_liviana = siguiente_mas_liviana(self.combo_calidad.currentData())
        cuadro = QMessageBox(self)
        cuadro.setIcon(QMessageBox.Icon.Warning)
        cuadro.setWindowTitle("El archivo es grande")
        cuadro.setText(
            f"El documento pesa {formatear_peso(peso)} y el límite de "
            f"adjunto es de {self._limite_mb} MB.")

        if mas_liviana is None:
            cuadro.setInformativeText(
                "Ya está guardado con la calidad más liviana. Vas a tener que "
                "mandarlo por otro medio, o firmar menos páginas por vez.")
            cuadro.exec()
            return True

        cuadro.setInformativeText(
            f"Se puede volver a guardar con calidad «{mas_liviana.nombre}»: "
            f"{mas_liviana.descripcion}")
        rehacer = cuadro.addButton(f"Guardar en «{mas_liviana.nombre}»",
                                   QMessageBox.ButtonRole.AcceptRole)
        cuadro.addButton("Dejarlo así", QMessageBox.ButtonRole.RejectRole)
        cuadro.exec()

        if cuadro.clickedButton() is not rehacer:
            return True

        i = self.combo_calidad.findData(mas_liviana.clave)
        if i >= 0:
            self.combo_calidad.setCurrentIndex(i)
        self._on_guardar()
        return False

    @pyqtSlot(str)
    def _emitir_guardado_listo(self, ruta: str):
        """Invocado en el siguiente ciclo del event loop (QueuedConnection)."""
        try:
            self.guardado_listo.emit(Path(ruta))
        except Exception as e:                       # noqa: BLE001
            log.error("Error al emitir guardado_listo: %s", e)

    @pyqtSlot(str)
    def _on_error(self, mensaje: str):
        log.error("Worker reportó error:\n%s", mensaje)
        self._set_guardando(False)

        resumen = mensaje.split("\n")[0]
        self.lbl_progreso_etapa.setText("Error al guardar")
        self.lbl_progreso_etapa.setProperty("rol", "error")
        repolish(self.lbl_progreso_etapa)
        self.lbl_error_detalle.setText(resumen)
        self.lbl_error_detalle.show()
        self.panel_progreso.show()

        QMessageBox.critical(
            self, "Error al guardar",
            f"No se pudo guardar el documento:\n\n{resumen}\n\n"
            "Revisá el log para el traceback completo.")

    @pyqtSlot()
    def _on_cancelar(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self.cancelado.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._on_cancelar()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            event.ignore()
            return
        if self._worker is not None:
            self._worker.wait()
            self._limpiar_worker()
        try:
            theme_signals.changed.disconnect(self._on_tema_cambiado)
        except (TypeError, RuntimeError):
            pass
        super().closeEvent(event)
