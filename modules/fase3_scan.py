"""
modules/fase3_scan.py
============================================================
Fase 3: stand-by post-impresión. Se digitaliza (o se carga) la hoja
firmada de CADA página seleccionada.

De una imagen a una cola
------------------------
Antes esta pantalla manejaba una sola imagen para una sola página.
Ahora muestra una fila por página elegida, cada una con su estado, su
miniatura y sus acciones. El botón "Continuar" se habilita recién
cuando todas las páginas tienen imagen.

Formas de asignar imágenes:
  - "Digitalizar" en una fila → escanea directo a esa página
  - "Digitalizar siguiente" → toma la próxima página pendiente y, al
    terminar, salta sola a la que sigue (flujo natural: firmás, escaneás,
    firmás la siguiente…)
  - "Cargar imágenes…" admite selección múltiple y las reparte en orden
    entre las páginas pendientes
  - Arrastrar varios archivos a la zona de drop hace lo mismo

Además
------
* Rotación por página (-90° / +90°): el escáner devuelve la hoja al
  revés muy seguido. La rotación se guarda en el modelo y se aplica al
  generar el PDF, sin tocar el archivo original.
* Aviso de orientación: si la imagen es apaisada y la página es vertical
  (o viceversa) se avisa en la fila, porque casi siempre es un escaneo
  mal orientado.
* closeEvent no bloquea la UI esperando al escáner.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPixmap, QTransform
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from modules.dispositivos import (
    ErrorDispositivo,
    listar_escaneres,
    verificar_escaneo_disponible,
)
from modules.escaner_qt import _WORKERS_VIVOS, WIAScanWorker
from modules.theme import SIZE, SPACE, repolish, theme_signals
from modules.trabajo import TrabajoFirma
from modules.ui import (
    AreaScroll,
    Aviso,
    BarraInferior,
    BarraSuperior,
    FilaAdaptable,
    IconoLabel,
    boton,
    boton_icono,
    etiqueta,
    icono_label,
    tarjeta,
)

EXTENSIONES_IMG = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp")
FILTRO_IMG = "Imágenes (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp)"

log = logging.getLogger(__name__)

# El worker de escaneo vive en modules/escaner_qt.py: lo comparten esta
# fase y la herramienta "Escanear a PDF". Se re-exporta para no romper
# los imports que ya lo tomaban desde acá.
__all__ = ["FilaPagina", "VistaEscaneo", "WIAScanWorker", "ZonaDrop"]


# ─────────────────────────────────────────────────────────────────────────
#  Zona de drag & drop
# ─────────────────────────────────────────────────────────────────────────
class ZonaDrop(QFrame):
    imagenes_soltadas = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("zonaDrop")
        self.setAcceptDrops(True)
        self.setMinimumHeight(90)
        self.setProperty("activo", "false")

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(SPACE["xs"])

        lay.addWidget(icono_label("abajo", 26, color="text_faint"), 0,
                      Qt.AlignmentFlag.AlignCenter)

        self.lbl_texto = etiqueta(
            "Arrastrá acá las imágenes escaneadas\n"
            "(se reparten en orden entre las páginas pendientes)",
            rol="hint", align=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_texto)

    def _set_activo(self, activo: bool):
        self.setProperty("activo", "true" if activo else "false")
        repolish(self)

    @staticmethod
    def _rutas_validas(mime) -> list[str]:
        return [
            u.toLocalFile() for u in mime.urls()
            if u.toLocalFile().lower().endswith(EXTENSIONES_IMG)
        ]

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls() and self._rutas_validas(e.mimeData()):
            e.acceptProposedAction()
            self._set_activo(True)
            return
        e.ignore()

    def dragLeaveEvent(self, e):
        self._set_activo(False)

    def dropEvent(self, e: QDropEvent):
        self._set_activo(False)
        rutas = self._rutas_validas(e.mimeData())
        if rutas:
            self.imagenes_soltadas.emit(sorted(rutas))


# ─────────────────────────────────────────────────────────────────────────
#  Fila de una página a firmar
# ─────────────────────────────────────────────────────────────────────────
class FilaPagina(QFrame):
    """Una página seleccionada, con su imagen, estado y acciones."""

    digitalizar_pedido = pyqtSignal(int)
    cargar_pedido      = pyqtSignal(int)
    quitar_pedido      = pyqtSignal(int)
    rotar_pedido       = pyqtSignal(int, int)   # (pagina, grados)

    THUMB = (58, 76)

    def __init__(self, pagina: int, ratio_pagina: float = 1.294, parent=None):
        super().__init__(parent)
        self.pagina = pagina
        self.ratio_pagina = ratio_pagina
        self._ruta: str | None = None

        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
        lay.setSpacing(SPACE["md"])

        self.lbl_thumb = QLabel()
        self.lbl_thumb.setObjectName("lienzoPagina")
        self.lbl_thumb.setFixedSize(*self.THUMB)
        self.lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_thumb)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(etiqueta(f"Página {pagina + 1}", rol="subtitulo"))

        fila_estado = QHBoxLayout()
        fila_estado.setSpacing(SPACE["xs"] + 2)
        self.icono_estado = IconoLabel("reloj", 14, color="text_faint")
        fila_estado.addWidget(self.icono_estado)
        self.lbl_estado = etiqueta("Pendiente de escaneo", rol="hint")
        fila_estado.addWidget(self.lbl_estado, 1)
        col.addLayout(fila_estado)

        self.lbl_aviso = etiqueta("", rol="error", wrap=True)
        self.lbl_aviso.hide()
        col.addWidget(self.lbl_aviso)
        col.addStretch()
        lay.addLayout(col, 1)

        # Rotar y quitar pasan a ser iconos: al lado de "Digitalizar" y
        # "Cargar…", cinco botones con texto amontonaban la fila y la
        # dejaban ilegible en ventanas angostas.
        self.btn_rotar_izq = boton_icono(
            "rotar-izq", tooltip="Rotar 90° a la izquierda",
            lado=SIZE["btn_sm"], tamano_icono=15,
            on_click=lambda: self.rotar_pedido.emit(self.pagina, -90))
        self.btn_rotar_der = boton_icono(
            "rotar-der", tooltip="Rotar 90° a la derecha",
            lado=SIZE["btn_sm"], tamano_icono=15,
            on_click=lambda: self.rotar_pedido.emit(self.pagina, 90))
        self.btn_quitar = boton_icono(
            "basura", tooltip="Quitar la imagen de esta página",
            lado=SIZE["btn_sm"], tamano_icono=15,
            on_click=lambda: self.quitar_pedido.emit(self.pagina))
        self.btn_quitar.setProperty("danger", "true")
        repolish(self.btn_quitar)
        self.btn_digitalizar = boton("Digitalizar", icono="escaner",
                                     variant="secondary",
                                     height=SIZE["btn_sm"],
                                     tooltip="Escanear la hoja firmada de esta página",
                                     on_click=lambda: self.digitalizar_pedido.emit(self.pagina))
        self.btn_cargar = boton("Cargar…", icono="imagen", variant="ghost",
                                height=SIZE["btn_sm"],
                                tooltip="Elegir un archivo de imagen para esta página",
                                on_click=lambda: self.cargar_pedido.emit(self.pagina))

        for b in (self.btn_rotar_izq, self.btn_rotar_der, self.btn_quitar,
                  self.btn_digitalizar, self.btn_cargar):
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)

        self.actualizar(None, 0)

    def actualizar(self, ruta: str | None, rotacion: int):
        """Refresca miniatura, estado y qué botones tienen sentido."""
        self._ruta = ruta
        tiene = bool(ruta)

        self.btn_rotar_izq.setVisible(tiene)
        self.btn_rotar_der.setVisible(tiene)
        self.btn_quitar.setVisible(tiene)
        self.btn_digitalizar.setVisible(not tiene)
        self.btn_cargar.setVisible(not tiene)

        if not tiene:
            self.lbl_thumb.clear()
            self.lbl_estado.setText("Pendiente de escaneo")
            self.lbl_estado.setProperty("rol", "hint")
            repolish(self.lbl_estado)
            self.icono_estado.set_icono("reloj", color="text_faint")
            self.icono_estado.setVisible(True)
            self.lbl_aviso.hide()
            self.setProperty("objectName", "card")
            return

        pm = QPixmap(ruta)
        if not pm.isNull():
            if rotacion:
                pm = pm.transformed(QTransform().rotate(rotacion),
                                    Qt.TransformationMode.SmoothTransformation)
            self.lbl_thumb.setPixmap(pm.scaled(
                *self.THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            self._evaluar_orientacion(pm)

        nombre = os.path.basename(ruta)
        sufijo = f"  ·  rotada {rotacion}°" if rotacion else ""
        self.lbl_estado.setText(f"{nombre}{sufijo}")
        self.lbl_estado.setProperty("rol", "ok")
        repolish(self.lbl_estado)
        self.icono_estado.set_icono("check-circulo", color="success")
        self.icono_estado.setVisible(True)

    def _evaluar_orientacion(self, pm: QPixmap):
        """Avisa si la imagen y la página tienen orientaciones opuestas.

        No bloquea nada: es casi siempre un escaneo al revés, y con un
        clic en "+90°" se arregla.
        """
        if pm.width() <= 0:
            self.lbl_aviso.hide()
            return
        ratio_img = pm.height() / pm.width()
        img_vertical = ratio_img >= 1
        pag_vertical = self.ratio_pagina >= 1
        if img_vertical != pag_vertical:
            self.lbl_aviso.setText(
                "La orientación no coincide con la página — probá rotarla.")
            self.lbl_aviso.show()
        else:
            self.lbl_aviso.hide()

    def marcar_escaneando(self, activo: bool):
        self.btn_digitalizar.setEnabled(not activo)
        self.btn_cargar.setEnabled(not activo)
        if activo:
            self.lbl_estado.setText("Escaneando…")
            self.lbl_estado.setProperty("rol", "ok")
            repolish(self.lbl_estado)
            self.icono_estado.set_icono("escaner", color="primary")
            self.icono_estado.setVisible(True)


# ─────────────────────────────────────────────────────────────────────────
#  Vista principal de la Fase 3
# ─────────────────────────────────────────────────────────────────────────
class VistaEscaneo(QWidget):
    """
    Señales:
      completado()  → todas las páginas tienen imagen y el usuario confirmó
      cancelar()    → volver al grid de páginas
    """

    completado = pyqtSignal()
    cancelar   = pyqtSignal()

    def __init__(self, trabajo: TrabajoFirma, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setObjectName("pantalla")
        self.setMinimumSize(560, 480)

        self.trabajo = trabajo
        self._filas: dict[int, FilaPagina] = {}
        self._worker: WIAScanWorker | None = None
        self._pagina_en_escaneo: int | None = None
        self._temporales: list[str] = []      # sólo los creados por esta vista
        self._entregado = False

        self._ratios = self._leer_ratios_paginas()
        self._construir_ui()
        self._refrescar()
        theme_signals.changed.connect(self._on_tema_cambiado)

    def _leer_ratios_paginas(self) -> dict[int, float]:
        """Proporción alto/ancho de cada página, para detectar escaneos
        con la orientación cambiada."""
        ratios: dict[int, float] = {}
        try:
            import fitz
            with fitz.open(str(self.trabajo.ruta_pdf)) as doc:
                for p in self.trabajo.paginas:
                    if 0 <= p < doc.page_count:
                        r = doc[p].rect
                        if r.width:
                            ratios[p] = r.height / r.width
        except Exception:
            pass
        return ratios

    # ── Construcción ───────────────────────────────────────────────────
    def _construir_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        nombre = os.path.basename(str(self.trabajo.ruta_pdf))
        cantidad = self.trabajo.cantidad
        plural = "s" if cantidad != 1 else ""
        self.cabecera = BarraSuperior(
            f"Escanear  ·  {cantidad} página{plural} "
            f"({self.trabajo.etiqueta_paginas()})  ·  {nombre}")
        self.cabecera.agregar(boton("Volver a páginas", variant="ghost",
                                    icono="chevron-izq",
                                    tooltip="Volver al listado de páginas (Esc)",
                                    on_click=self.cancelar.emit))
        raiz.addWidget(self.cabecera)

        cuerpo = AreaScroll(margenes=(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"]),
                            spacing=SPACE["md"])
        lay = cuerpo.lay

        lay.addWidget(etiqueta(
            f"Se imprimieron las páginas {self.trabajo.etiqueta_paginas()}. "
            "Firmá cada hoja y digitalizala, o cargá las imágenes desde el disco. "
            "Podés hacerlo en cualquier orden.",
            rol="cuerpo", wrap=True))

        lay.addWidget(Aviso(
            f"El escaneo WIA se hace en color a {WIAScanWorker.DPI_SCAN} DPI "
            "(máxima calidad). Podés ajustarlo en el diálogo del escáner.",
            tono="info", icono_nombre="bombilla"))

        # Acciones globales
        acciones = FilaAdaptable(breakpoint_px=560, spacing=SPACE["sm"])
        self.btn_siguiente = boton("Digitalizar siguiente pendiente",
                                   icono="escaner",
                                   min_w=230,
                                   tooltip="Escanea la próxima página sin imagen",
                                   on_click=self._digitalizar_siguiente)
        acciones.agregar(self.btn_siguiente)
        acciones.agregar(boton("Cargar imágenes…", icono="imagen",
                               variant="secondary",
                               tooltip="Elegí uno o varios archivos; se reparten "
                                       "entre las páginas pendientes",
                               on_click=self._cargar_varias))
        acciones.agregar_stretch()
        lay.addWidget(acciones)

        self.zona_drop = ZonaDrop()
        self.zona_drop.imagenes_soltadas.connect(self._repartir_imagenes)
        lay.addWidget(self.zona_drop)

        # Filas por página
        contenedor_filas, self._lay_filas = tarjeta(padding=0, spacing=SPACE["sm"])
        contenedor_filas.setObjectName("")   # sin fondo propio: son tarjetas sueltas
        for p in self.trabajo.paginas:
            fila = FilaPagina(p, self._ratios.get(p, 1.294))
            fila.digitalizar_pedido.connect(self._digitalizar_pagina)
            fila.cargar_pedido.connect(self._cargar_para_pagina)
            fila.quitar_pedido.connect(self._quitar_imagen)
            fila.rotar_pedido.connect(self._rotar)
            self._filas[p] = fila
            self._lay_filas.addWidget(fila)
        lay.addWidget(contenedor_filas)
        lay.addStretch()
        raiz.addWidget(cuerpo, 1)

        self.pie = BarraInferior("")
        self.btn_usar = boton("Continuar", icono="flecha-der",
                              height=SIZE["btn_lg"],
                              enabled=False, on_click=self._on_continuar)
        self.pie.agregar(self.btn_usar)
        raiz.addWidget(self.pie)

    # ── Estado ─────────────────────────────────────────────────────────
    def _refrescar(self):
        for p, fila in self._filas.items():
            fila.actualizar(self.trabajo.imagenes.get(p), self.trabajo.rotacion(p))

        completo = self.trabajo.completo
        self.btn_usar.setEnabled(completo)
        pendientes = self.trabajo.paginas_pendientes()
        self.btn_siguiente.setEnabled(bool(pendientes))

        if completo:
            self.pie.set_estado(self.trabajo.descripcion_progreso(),
                                rol="ok", tono="ok")
        else:
            from modules.trabajo import formatear_paginas
            self.pie.set_estado(
                f"{self.trabajo.descripcion_progreso()}  ·  "
                f"faltan: {formatear_paginas(pendientes)}")

    # ── Asignación de imágenes ─────────────────────────────────────────
    def _validar_imagen(self, ruta: str) -> bool:
        if not ruta or not Path(ruta).exists():
            QMessageBox.warning(self, "Imagen no encontrada",
                                f"No se pudo leer:\n{ruta}")
            return False
        if QPixmap(ruta).isNull():
            QMessageBox.warning(
                self, "Formato no soportado",
                f"No se pudo interpretar la imagen:\n{os.path.basename(ruta)}")
            return False
        return True

    def _asignar(self, pagina: int, ruta: str) -> bool:
        if not self._validar_imagen(ruta):
            return False
        try:
            self.trabajo.asignar_imagen(pagina, ruta)
        except ValueError as e:
            QMessageBox.warning(self, "Página inválida", str(e))
            return False
        self._refrescar()
        return True

    def _repartir_imagenes(self, rutas: list[str]):
        """Asigna una lista de archivos a las páginas pendientes, en orden."""
        pendientes = self.trabajo.paginas_pendientes()
        if not pendientes:
            QMessageBox.information(
                self, "Sin páginas pendientes",
                "Todas las páginas ya tienen imagen.\n\n"
                "Quitá alguna si querés reemplazarla.")
            return

        asignadas = 0
        for ruta, pagina in zip(rutas, pendientes):
            if self._asignar(pagina, ruta):
                asignadas += 1

        sobrantes = len(rutas) - len(pendientes)
        if sobrantes > 0:
            QMessageBox.information(
                self, "Sobraron imágenes",
                f"Se asignaron {asignadas} imagen(es) a las páginas pendientes.\n"
                f"Quedaron {sobrantes} sin usar: sólo había {len(pendientes)} "
                "página(s) esperando.")

    def _cargar_varias(self):
        rutas, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar imágenes escaneadas",
            os.path.expanduser("~"), FILTRO_IMG)
        if rutas:
            self._repartir_imagenes(sorted(rutas))

    def _cargar_para_pagina(self, pagina: int):
        ruta, _ = QFileDialog.getOpenFileName(
            self, f"Imagen para la página {pagina + 1}",
            os.path.expanduser("~"), FILTRO_IMG)
        if ruta:
            self._asignar(pagina, ruta)

    def _quitar_imagen(self, pagina: int):
        self.trabajo.quitar_imagen(pagina)
        self._refrescar()

    def _rotar(self, pagina: int, grados: int):
        try:
            self.trabajo.rotar(pagina, grados)
        except ValueError as e:
            QMessageBox.warning(self, "No se puede rotar", str(e))
            return
        self._refrescar()

    # ── Escaneo WIA ────────────────────────────────────────────────────
    def _digitalizar_siguiente(self):
        pagina = self.trabajo.siguiente_pendiente()
        if pagina is None:
            return
        self._digitalizar_pagina(pagina)

    def _digitalizar_pagina(self, pagina: int):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Escaneo en curso",
                "Ya hay un escaneo abierto. Terminalo o cancelalo antes de "
                "empezar otro.")
            return

        # Un solo chequeo cubre "no es Windows", "falta pywin32" y "no hay
        # escáner conectado", cada uno con su mensaje y su sugerencia.
        try:
            verificar_escaneo_disponible()
        except ErrorDispositivo as e:
            QMessageBox.warning(self, "No se puede escanear", e.texto_completo())
            return

        # Con más de un escáner instalado, dejamos que elija: antes se
        # usaba siempre el predeterminado de Windows, sin decir cuál era.
        elegir = len(listar_escaneres()) > 1

        self._pagina_en_escaneo = pagina
        fila = self._filas.get(pagina)
        if fila:
            fila.marcar_escaneando(True)
        self.btn_siguiente.setEnabled(False)
        self.pie.set_estado(f"Escaneando la página {pagina + 1}…", rol="ok")

        worker = WIAScanWorker(elegir_dispositivo=elegir)
        self._worker = worker
        _WORKERS_VIVOS.add(worker)
        worker.finished.connect(lambda: _WORKERS_VIVOS.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.scan_completado.connect(self._on_scan_completado)
        worker.scan_cancelado.connect(self._on_scan_cancelado)
        worker.scan_error.connect(self._on_wia_error)
        worker.start()

    def _on_scan_completado(self, ruta: str):
        self._temporales.append(ruta)
        pagina = self._pagina_en_escaneo
        self._pagina_en_escaneo = None
        if pagina is None:
            return
        self._asignar(pagina, ruta)

        # Salta sola a la próxima pendiente: el usuario ya está frente al
        # escáner con la siguiente hoja en la mano.
        siguiente = self.trabajo.siguiente_pendiente(pagina)
        if siguiente is not None:
            self.pie.set_estado(
                f"Página {pagina + 1} lista. Siguiente pendiente: "
                f"página {siguiente + 1}.", rol="ok")
            fila = self._filas.get(siguiente)
            if fila:
                fila.btn_digitalizar.setFocus()
        self._refrescar()

    def _on_scan_cancelado(self):
        pagina = self._pagina_en_escaneo
        self._pagina_en_escaneo = None
        if pagina is not None and pagina in self._filas:
            self._filas[pagina].marcar_escaneando(False)
        self._refrescar()

    def _on_wia_error(self, error):
        """Muestra el error ya traducido por la capa de dispositivos."""
        self._on_scan_cancelado()
        texto = (error.texto_completo() if isinstance(error, ErrorDispositivo)
                 else str(error))
        log.warning("Error de escaneo: %s", texto)
        QMessageBox.warning(self, "Error al digitalizar", texto)

    # ── Salida ─────────────────────────────────────────────────────────
    def _on_continuar(self):
        if not self.trabajo.completo:
            return
        self._entregado = True
        self.completado.emit()

    def _on_tema_cambiado(self, _modo: str):
        self._refrescar()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelar.emit()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) \
                and self.btn_usar.isEnabled():
            self._on_continuar()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        # No esperamos al worker: el diálogo WIA es modal del sistema y
        # bloquearía la app entera. El thread se limpia solo (_WORKERS_VIVOS).
        try:
            theme_signals.changed.disconnect(self._on_tema_cambiado)
        except (TypeError, RuntimeError):
            pass
        if not self._entregado:
            en_uso = set(self.trabajo.imagenes.values())
            for f in self._temporales:
                if f not in en_uso:
                    try:
                        os.remove(f)
                    except OSError:
                        pass
        super().closeEvent(event)
