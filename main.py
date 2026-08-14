"""
PDF Sign Assistant — main.py
============================================================
Flujo principal:
  1. Pantalla de inicio: botón "Abrir PDF" + lista de trabajos guardados.
  2. Panel activo cuando hay un PDF en trabajo (cancelar / trabajar páginas).
  3. El panel activo delega a:
       fase1_preview → fase2_print → fase3_scan → fase_guardar
  4. Al confirmar se añade a la lista de guardados (con fecha/hora).
  5. Doble clic en un guardado → lo reabre para re-editar.
  6. Seleccionar un guardado → habilita Editar y Enviar correo.
  7. ⚙ → DialogoAjustes (correo emisor).
  8. 🌙 / ☀ → alterna modo claro y oscuro (queda guardado en config.json).
  9. 📂 → abre la carpeta de documentos firmados.
 10. closeEvent → limpia _envio_temp/ antes de salir.

Atajos de teclado:
  Ctrl+O  abrir PDF          Ctrl+F  buscar en guardados
  Ctrl+E  enviar por correo  Ctrl+D  alternar tema
  F5      recargar lista     Enter   editar el seleccionado

NOTA PyInstaller:
  - Instalar dependencias antes de buildear:  pip install -r requirements.txt
  - Las rutas se resuelven vía modules.setup.get_base_dir() para que
    funcione igual como script y como .exe congelado.
"""

from __future__ import annotations

import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

from modules.errores import instalar as instalar_manejador_errores
from modules.fase1_preview import VistaPrevisualizacion
from modules.setup import (
    BASE_DIR,
    CARPETA_FIRMADO,
    CARPETA_TRABAJO,
    CONFIG_PATH,
    cargar_config,
    configurar_logging,
    guardar_config,
    limpiar_trabajos_huerfanos,
    setup_directories,
)
from modules.theme import SPACE, THEME, apply_theme, current_mode
from modules.trabajo import TrabajoFirma
from modules.ui import (
    FilaAdaptable,
    abrir_en_sistema,
    boton,
    etiqueta,
    separador,
    tarjeta,
)
from modules.version import APP_NOMBRE, __version__

setup_directories()
log = logging.getLogger("psa.main")

# Limpiar la carpeta temporal de envíos de sesiones anteriores
try:
    from modules.fase4_email import limpiar_temp_al_iniciar
    limpiar_temp_al_iniciar(CARPETA_FIRMADO)
except Exception:
    pass


# ── Panel del PDF activo ──────────────────────────────────────────────────────

def _panel_activo(ruta: Path, total_paginas: int,
                  on_trabajar, on_cancelar) -> QWidget:
    """Tarjeta con el PDF en curso y sus dos acciones."""
    panel, lay = tarjeta(acento=True, padding=SPACE["lg"], spacing=SPACE["md"])
    panel.setObjectName("panelActivo")

    fila_info = QHBoxLayout()
    fila_info.setSpacing(SPACE["md"])

    icono = etiqueta("📄")
    icono.setStyleSheet("font-size: 22px;")
    icono.setFixedWidth(32)
    icono.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
    fila_info.addWidget(icono)

    col = QVBoxLayout()
    col.setSpacing(2)
    col.addWidget(etiqueta("PDF EN TRABAJO", rol="seccion"))
    col.addWidget(etiqueta(ruta.name, rol="subtitulo", wrap=True))
    detalle = str(ruta.parent)
    if total_paginas:
        plural = "s" if total_paginas != 1 else ""
        detalle = f"{total_paginas} página{plural}  ·  {detalle}"
    col.addWidget(etiqueta(detalle, rol="hint", wrap=True))
    fila_info.addLayout(col, 1)
    lay.addLayout(fila_info)

    acciones = FilaAdaptable(breakpoint_px=440, spacing=SPACE["sm"])
    acciones.agregar(boton("Elegir páginas  →", min_w=190, height=40,
                           on_click=on_trabajar))
    acciones.agregar_stretch()
    acciones.agregar(boton("✕  Cancelar", variant="danger", height=40,
                           on_click=on_cancelar))
    lay.addWidget(acciones)
    return panel


# ── Item de la lista de guardados ─────────────────────────────────────────────

ROL_NOMBRE = int(Qt.ItemDataRole.UserRole) + 1
ROL_FECHA  = int(Qt.ItemDataRole.UserRole) + 2


class ItemGuardado(QListWidgetItem):
    def __init__(self, ruta: Path, mtime: float | None = None):
        super().__init__()
        self.ruta = ruta
        try:
            ts = ruta.stat().st_mtime if mtime is None else mtime
            fecha = datetime.fromtimestamp(ts).strftime("%d/%m/%Y  ·  %H:%M")
        except OSError:
            fecha = ""
        # El texto plano queda como respaldo (búsqueda/accesibilidad);
        # el dibujo real lo hace _DelegadoDocumento.
        self.setText(f"{ruta.name}\n{fecha}")
        self.setData(ROL_NOMBRE, ruta.name)
        self.setData(ROL_FECHA, fecha)
        self.setSizeHint(QSize(0, 54))
        self.setToolTip(str(ruta))


class _DelegadoDocumento(QStyledItemDelegate):
    """Dibuja cada fila con jerarquía: nombre en primer plano y fecha
    atenuada debajo. Con el texto por defecto de QListWidget ambas
    líneas salían con el mismo peso y tamaño."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""   # el texto lo dibujamos nosotros

        widget = opt.widget
        estilo = widget.style() if widget is not None else QApplication.style()
        estilo.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        nombre = index.data(ROL_NOMBRE) or ""
        fecha = index.data(ROL_FECHA) or ""
        rect = opt.rect.adjusted(SPACE["md"], SPACE["sm"], -SPACE["md"], -SPACE["sm"])
        mitad = rect.height() // 2

        painter.save()
        fuente = QFont(opt.font)
        fuente.setWeight(QFont.Weight.DemiBold)
        painter.setFont(fuente)
        painter.setPen(QColor(THEME["text"]))
        metricas = QFontMetrics(fuente)
        painter.drawText(
            QRect(rect.left(), rect.top(), rect.width(), mitad),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metricas.elidedText(nombre, Qt.TextElideMode.ElideMiddle, rect.width()),
        )

        # El tema define los tamaños en px vía QSS, así que pointSizeF()
        # puede valer -1: hay que reducir sobre la unidad que sí exista.
        fuente_fecha = QFont(opt.font)
        if opt.font.pointSizeF() > 0:
            fuente_fecha.setPointSizeF(max(6.0, opt.font.pointSizeF() - 1))
        else:
            fuente_fecha.setPixelSize(max(9, opt.font.pixelSize() - 1))
        painter.setFont(fuente_fecha)
        painter.setPen(QColor(THEME["text_muted"]))
        painter.drawText(
            QRect(rect.left(), rect.top() + mitad, rect.width(), mitad),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            fecha,
        )
        painter.restore()


# ── Ventana principal ─────────────────────────────────────────────────────────

class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NOMBRE}  v{__version__}")
        # Mínimo chico a propósito: la UI se adapta y no obliga a tener
        # una pantalla grande.
        self.setMinimumSize(460, 420)
        self.resize(880, 660)

        self.config = cargar_config()
        # Todo el estado del trabajo en curso vive en TrabajoFirma
        self._trabajo: TrabajoFirma | None = None
        self._vista_preview = None
        self._vista_escaneo = None
        self._vista_guardar = None

        self._worker_update = None
        self._build_ui()
        self._registrar_atajos()
        self._recargar_guardados()
        self._vigilar_carpeta()

        # Comprobación diferida: que la ventana abra primero. Buscar
        # actualizaciones nunca debe retrasar el arranque.
        QTimer.singleShot(3000, self._comprobar_actualizaciones_auto)

    # ── Cierre de la app ──────────────────────────────────────────────────
    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        """Limpia la carpeta temporal de envíos y cierra las vistas abiertas."""
        try:
            from modules.fase4_email import limpiar_temp_al_salir
            limpiar_temp_al_salir(CARPETA_FIRMADO)
        except Exception:
            pass
        self._cerrar_vistas_abiertas()
        super().closeEvent(event)

    # ── Construcción de UI ────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("pantalla")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["md"])
        root.setSpacing(SPACE["md"])

        root.addWidget(self._construir_header())
        root.addWidget(separador())

        # Panel del PDF activo (oculto mientras no hay ninguno)
        self.panel_activo_container = QWidget()
        self.panel_activo_container.setVisible(False)
        self._lay_panel = QVBoxLayout(self.panel_activo_container)
        self._lay_panel.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.panel_activo_container)

        root.addWidget(self._construir_encabezado_lista())
        root.addWidget(self._construir_lista(), 1)
        root.addWidget(self._construir_acciones())

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Listo — abrí un PDF para comenzar.")

    def _construir_header(self) -> QWidget:
        header = FilaAdaptable(breakpoint_px=560, spacing=SPACE["sm"])

        titulo = QWidget()
        lay_t = QHBoxLayout(titulo)
        lay_t.setContentsMargins(0, 0, 0, 0)
        lay_t.setSpacing(SPACE["sm"])

        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {THEME['primary']}; font-size: 10px;")
        self._dot.setFixedWidth(12)
        lay_t.addWidget(self._dot)

        lbl_titulo = etiqueta("PDF Sign Assistant", rol="titulo")
        lbl_titulo.setSizePolicy(QSizePolicy.Policy.Ignored,
                                 QSizePolicy.Policy.Preferred)
        lay_t.addWidget(lbl_titulo, 1)
        header.agregar(titulo, 1)

        oscuro = current_mode() == "dark"
        self.btn_tema = boton("☀" if oscuro else "🌙", variant="ghost", fixed_w=42,
                              tooltip="Cambiar tema (Ctrl+D)",
                              on_click=self._toggle_tema)
        header.agregar(self.btn_tema)

        self.btn_ajustes = boton("⚙", variant="ghost", fixed_w=42,
                                 tooltip="Ajustes", on_click=self._abrir_ajustes)
        header.agregar(self.btn_ajustes)

        self.btn_abrir = boton("＋  Abrir PDF", min_w=140,
                               tooltip="Abrir un PDF para trabajar (Ctrl+O)",
                               on_click=self.abrir_pdf)
        header.agregar(self.btn_abrir)
        return header

    def _construir_encabezado_lista(self) -> QWidget:
        fila = QWidget()
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE["sm"])

        lay.addWidget(etiqueta("TRABAJOS GUARDADOS", rol="seccion"))
        lay.addStretch()

        self.input_buscar = QLineEdit()
        self.input_buscar.setPlaceholderText("Buscar…")
        self.input_buscar.setClearButtonEnabled(True)
        self.input_buscar.setMaximumWidth(220)
        self.input_buscar.textChanged.connect(self._filtrar_lista)
        lay.addWidget(self.input_buscar)

        self.lbl_contador = etiqueta("", rol="hint")
        lay.addWidget(self.lbl_contador)
        return fila

    def _construir_lista(self) -> QWidget:
        # QStackedWidget: lista y estado vacío ocupan el mismo lugar, así
        # no queda el hueco muerto que dejaba el layout anterior.
        self.stack = QStackedWidget()

        self.lista_guardados = QListWidget()
        self.lista_guardados.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.lista_guardados.setAlternatingRowColors(False)
        self.lista_guardados.setUniformItemSizes(True)
        self.lista_guardados.setItemDelegate(_DelegadoDocumento(self.lista_guardados))
        self.lista_guardados.itemDoubleClicked.connect(self._reabrir_guardado)
        self.lista_guardados.itemSelectionChanged.connect(self._on_seleccion_guardado)
        self.stack.addWidget(self.lista_guardados)

        self.panel_vacio, lay_v = tarjeta(padding=SPACE["xl"], spacing=SPACE["sm"])
        self.panel_vacio.setObjectName("panelVacio")
        lay_v.addStretch()
        icono = etiqueta("📋", align=Qt.AlignmentFlag.AlignCenter)
        icono.setStyleSheet("font-size: 30px;")
        lay_v.addWidget(icono)
        lay_v.addWidget(etiqueta("Sin documentos firmados todavía",
                                 rol="subtitulo",
                                 align=Qt.AlignmentFlag.AlignCenter))
        lay_v.addWidget(etiqueta(
            "Abrí un PDF con el botón de arriba para comenzar.\n"
            "Los documentos que guardes aparecerán acá.",
            rol="hint", wrap=True, align=Qt.AlignmentFlag.AlignCenter))
        lay_v.addStretch()
        self.stack.addWidget(self.panel_vacio)
        return self.stack

    def _construir_acciones(self) -> QWidget:
        acciones = FilaAdaptable(breakpoint_px=620, spacing=SPACE["sm"])

        self.btn_reabrir = boton("✏️  Editar seleccionado", variant="secondary",
                                 enabled=False, tooltip="Volver a firmar (Enter)",
                                 on_click=self._reabrir_desde_boton)
        acciones.agregar(self.btn_reabrir)

        self.btn_email = boton("✉️  Enviar por correo", variant="secondary",
                               enabled=False, tooltip="Enviar el documento (Ctrl+E)",
                               on_click=self._enviar_correo)
        acciones.agregar(self.btn_email)
        acciones.agregar_stretch()

        self.btn_carpeta = boton("📂  Abrir carpeta", variant="ghost",
                                 tooltip=str(CARPETA_FIRMADO),
                                 on_click=self._abrir_carpeta_firmados)
        acciones.agregar(self.btn_carpeta)
        return acciones

    def _registrar_atajos(self):
        for secuencia, funcion in (
            ("Ctrl+O", self.abrir_pdf),
            ("Ctrl+E", self._enviar_correo),
            ("Ctrl+D", self._toggle_tema),
            ("Ctrl+F", lambda: self.input_buscar.setFocus()),
            ("F5", self._recargar_guardados),
            ("Return", self._reabrir_desde_boton),
        ):
            QShortcut(QKeySequence(secuencia), self, activated=funcion)

    # ── Tema ──────────────────────────────────────────────────────────────
    def _toggle_tema(self):
        nuevo = "dark" if current_mode() == "light" else "light"
        apply_theme(QApplication.instance(), nuevo)
        self.btn_tema.setText("☀" if nuevo == "dark" else "🌙")
        self._dot.setStyleSheet(f"color: {THEME['primary']}; font-size: 10px;")

        self.config["tema"] = nuevo
        try:
            guardar_config(self.config, CONFIG_PATH)
        except OSError:
            pass
        self.status.showMessage(
            f"Tema {'oscuro' if nuevo == 'dark' else 'claro'} activado.")

    # ── Lista de guardados ────────────────────────────────────────────────
    def _recargar_guardados(self):
        """Relee pdfs_firmados/ y reconstruye la lista.

        Un solo stat() por archivo: se reutiliza el mtime del ordenamiento
        para construir el item (antes se llamaba dos veces por archivo).
        """
        seleccionado = self._item_seleccionado()
        nombre_sel = seleccionado.ruta.name if seleccionado else None

        archivos = []
        for pdf in CARPETA_FIRMADO.glob("*.pdf"):
            try:
                archivos.append((pdf.stat().st_mtime, pdf))
            except OSError:
                continue
        archivos.sort(key=lambda par: par[0], reverse=True)

        self.lista_guardados.clear()
        for mtime, pdf in archivos:
            self.lista_guardados.addItem(ItemGuardado(pdf, mtime))

        if nombre_sel:
            for i in range(self.lista_guardados.count()):
                if self.lista_guardados.item(i).ruta.name == nombre_sel:
                    self.lista_guardados.setCurrentRow(i)
                    break

        self._filtrar_lista(self.input_buscar.text())

    def _vigilar_carpeta(self):
        """Refresca la lista si la carpeta cambia desde afuera (con debounce
        para no recargar una vez por archivo en copias masivas)."""
        self._watcher = QFileSystemWatcher([str(CARPETA_FIRMADO)], self)
        self._timer_recarga = QTimer(self)
        self._timer_recarga.setSingleShot(True)
        self._timer_recarga.setInterval(400)
        self._timer_recarga.timeout.connect(self._recargar_guardados)
        self._watcher.directoryChanged.connect(lambda _p: self._timer_recarga.start())

    def _filtrar_lista(self, texto: str = ""):
        texto = (texto or "").strip().lower()
        visibles = 0
        for i in range(self.lista_guardados.count()):
            item = self.lista_guardados.item(i)
            coincide = texto in item.ruta.name.lower()
            item.setHidden(not coincide)
            visibles += coincide

        total = self.lista_guardados.count()
        self.stack.setCurrentWidget(
            self.lista_guardados if total else self.panel_vacio)

        if not total:
            self.lbl_contador.setText("")
        elif texto:
            self.lbl_contador.setText(f"{visibles} de {total}")
        else:
            self.lbl_contador.setText(
                f"{total} documento{'s' if total != 1 else ''}")

    def _agregar_item_guardado(self, ruta: Path):
        self._recargar_guardados()
        for i in range(self.lista_guardados.count()):
            if self.lista_guardados.item(i).ruta == ruta:
                self.lista_guardados.setCurrentRow(i)
                self.lista_guardados.scrollToItem(self.lista_guardados.item(i))
                break

    # ── Selección ─────────────────────────────────────────────────────────
    def _on_seleccion_guardado(self):
        tiene = bool(self.lista_guardados.selectedItems())
        self.btn_reabrir.setEnabled(tiene)
        self.btn_email.setEnabled(tiene)

    def _item_seleccionado(self) -> ItemGuardado | None:
        items = self.lista_guardados.selectedItems()
        return items[0] if items else None      # type: ignore[return-value]

    # ── Ajustes ───────────────────────────────────────────────────────────
    def _abrir_ajustes(self):
        from modules.settings import DialogoAjustes
        dlg = DialogoAjustes(config_path=CONFIG_PATH, config=self.config, parent=self)
        dlg.buscar_actualizaciones.connect(
            lambda: self._comprobar_actualizaciones(manual=True))
        if dlg.exec():
            # Conservamos el tema actual: el diálogo no lo edita.
            dlg.config["tema"] = self.config.get("tema", current_mode())
            self.config = dlg.config
            self.status.showMessage(
                f"Ajustes guardados — correo: {self.config.get('email_user', '')}")

    # ── Actualizaciones ───────────────────────────────────────────────────
    def _comprobar_actualizaciones_auto(self):
        """Comprobación silenciosa al arrancar (como mucho, una vez por día)."""
        from modules.actualizador import toca_comprobar

        if not toca_comprobar(self.config):
            return
        self._comprobar_actualizaciones(manual=False)

    def _comprobar_actualizaciones(self, manual: bool = False):
        """Consulta si hay versión nueva.

        `manual` distingue el pedido explícito del usuario (que espera
        una respuesta aunque sea "ya estás al día") de la comprobación
        automática, que sólo habla si hay algo que decir.
        """
        from modules.actualizador import (
            REPO_DEFECTO,
            WorkerComprobar,
            marcar_comprobacion,
        )

        if self._worker_update is not None and self._worker_update.isRunning():
            return

        if manual:
            self.status.showMessage("Buscando actualizaciones…")

        marcar_comprobacion(self.config)
        try:
            guardar_config(self.config, CONFIG_PATH)
        except OSError:
            pass

        # El repositorio es configurable: permite apuntar a un servidor
        # interno que exponga la misma forma de respuesta.
        self._worker_update = WorkerComprobar(
            self.config.get("repo_actualizaciones") or REPO_DEFECTO)
        self._worker_update.resultado.connect(
            lambda info: self._on_resultado_update(info, manual))
        self._worker_update.start()

    def _on_resultado_update(self, info, manual: bool):
        from modules.actualizador import (
            DialogoActualizacion,
            esta_ignorada,
            hay_version_nueva,
        )

        if info is None:
            if manual:
                QMessageBox.information(
                    self, "Sin conexión",
                    "No se pudo consultar si hay actualizaciones.\n\n"
                    "Revisá tu conexión a internet y volvé a intentarlo.")
                self.status.showMessage("No se pudo buscar actualizaciones.")
            return

        if not hay_version_nueva(__version__, info.version):
            if manual:
                QMessageBox.information(
                    self, "Todo al día",
                    f"Ya tenés la última versión ({__version__}).")
            self.status.showMessage(f"Versión {__version__} — al día.")
            return

        # En la comprobación automática respetamos el "omitir esta versión";
        # si la pidió el usuario, se la mostramos igual.
        if not manual and esta_ignorada(self.config, info.version):
            return

        log.info("Actualización disponible: %s → %s", __version__, info.version)
        self.status.showMessage(f"Actualización disponible: {info.version}")

        dlg = DialogoActualizacion(info, parent=self)
        dlg.omitir_version.connect(self._omitir_version)
        dlg.exec()

    def _omitir_version(self, version: str):
        self.config["version_ignorada"] = version
        try:
            guardar_config(self.config, CONFIG_PATH)
        except OSError:
            pass
        self.status.showMessage(f"No se volverá a avisar de la versión {version}.")

    # ── Abrir PDF ─────────────────────────────────────────────────────────
    def abrir_pdf(self):
        if self._trabajo is not None:
            QMessageBox.information(
                self, "PDF en proceso",
                f"Ya hay un PDF en trabajo:\n{self._trabajo.ruta_pdf.name}\n\n"
                "Cancelá o finalizá el trabajo actual antes de abrir otro.")
            return

        ruta_str, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar PDF", str(Path.home()), "Archivos PDF (*.pdf)")
        if not ruta_str:
            return

        origen = Path(ruta_str)
        total_paginas = self._validar_pdf(origen)
        if total_paginas is None:
            return

        destino = CARPETA_TRABAJO / origen.name
        if destino.exists():
            ts = datetime.now().strftime("%H%M%S")
            destino = CARPETA_TRABAJO / f"{origen.stem}_{ts}{origen.suffix}"

        try:
            shutil.copy2(origen, destino)
        except OSError as e:
            QMessageBox.critical(self, "Error al copiar", str(e))
            return

        self._activar_pdf(destino, total_paginas)
        plural = "s" if total_paginas != 1 else ""
        self.status.showMessage(
            f"PDF cargado: {destino.name} ({total_paginas} página{plural})")

    def _validar_pdf(self, ruta: Path) -> int | None:
        """Valida el PDF antes de copiarlo y devuelve su cantidad de páginas.

        Devuelve None si está dañado, protegido o vacío: así se avisa acá
        en vez de fallar más adelante, en mitad del flujo.
        """
        try:
            import fitz
        except ImportError:
            return 0        # sin fitz no podemos contar; el flujo sigue
        try:
            with fitz.open(str(ruta)) as doc:
                if doc.needs_pass:
                    QMessageBox.warning(
                        self, "PDF protegido",
                        "El documento está protegido con contraseña.\n\n"
                        "Quitale la protección y volvé a intentarlo.")
                    return None
                if doc.page_count == 0:
                    QMessageBox.warning(self, "PDF vacío",
                                        "El documento no tiene páginas.")
                    return None
                return doc.page_count
        except Exception as e:                       # noqa: BLE001
            QMessageBox.critical(
                self, "No se pudo abrir el PDF",
                f"El archivo parece dañado o no es un PDF válido:\n\n{e}")
            return None

    def _activar_pdf(self, ruta: Path, total_paginas: int = 0):
        self._trabajo = TrabajoFirma(ruta_pdf=ruta, total_paginas=total_paginas)
        log.info("Trabajo iniciado sobre %s (%d páginas)", ruta.name, total_paginas)
        self._limpiar_panel_activo()
        self._lay_panel.addWidget(
            _panel_activo(ruta, total_paginas,
                          on_trabajar=self._iniciar_flujo_trabajo,
                          on_cancelar=self._cancelar_trabajo))
        self.panel_activo_container.setVisible(True)
        self.btn_abrir.setEnabled(False)

    def _limpiar_panel_activo(self):
        while self._lay_panel.count():
            item = self._lay_panel.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()

    # ── Cancelar trabajo ──────────────────────────────────────────────────
    def _cancelar_trabajo(self):
        if self._trabajo is None:
            return

        avance = ""
        if self._trabajo.paginas:
            avance = f"\n\nProgreso: {self._trabajo.descripcion_progreso()}."
        resp = QMessageBox.question(
            self, "Cancelar trabajo",
            f"¿Seguro que querés salir de:\n{self._trabajo.ruta_pdf.name}?"
            f"{avance}\n\nLos cambios no guardados se perderán.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if resp != QMessageBox.StandardButton.Yes:
            return
        try:
            self._trabajo.ruta_pdf.unlink(missing_ok=True)
        except OSError:
            pass
        self._cerrar_vistas_abiertas()
        self._desactivar_panel()
        self.status.showMessage("Trabajo cancelado.")

    def _desactivar_panel(self):
        self._trabajo = None
        self._limpiar_panel_activo()
        self.panel_activo_container.setVisible(False)
        self.btn_abrir.setEnabled(True)

    def _cerrar_vistas_abiertas(self):
        for attr in ("_vista_preview", "_vista_escaneo", "_vista_guardar"):
            self._cerrar_vista(attr)

    def _cerrar_vista(self, attr: str):
        vista = getattr(self, attr, None)
        if vista is not None:
            vista.close()
            vista.deleteLater()
            setattr(self, attr, None)

    # ── Flujo de trabajo ──────────────────────────────────────────────────
    #  Las cuatro fases comparten un mismo TrabajoFirma: la selección de
    #  páginas, las imágenes y las rotaciones viven ahí y no en atributos
    #  sueltos de la ventana. Volver atrás conserva lo ya hecho.

    def _iniciar_flujo_trabajo(self):
        if self._trabajo is None:
            return
        self._cerrar_vista("_vista_preview")
        self._vista_preview = VistaPrevisualizacion(
            str(self._trabajo.ruta_pdf),
            seleccion_inicial=self._trabajo.paginas,
            parent=self)
        self._vista_preview.setWindowTitle("PDF Sign Assistant — Elegir páginas")
        self._vista_preview.resize(980, 700)
        self._vista_preview.paginas_seleccionadas.connect(self._on_paginas_elegidas)
        self._vista_preview.cancelar.connect(self._on_preview_cancelado)
        self._vista_preview.show()

    def _on_paginas_elegidas(self, paginas: list):
        if self._trabajo is None:
            return
        self._trabajo.set_paginas(paginas)
        self._cerrar_vista("_vista_preview")

        etiqueta_pags = self._trabajo.etiqueta_paginas()
        log.info("Imprimiendo páginas %s de %s",
                 etiqueta_pags, self._trabajo.ruta_pdf.name)

        from modules.fase2_print import ImpresionPagina
        if not ImpresionPagina.imprimir(str(self._trabajo.ruta_pdf),
                                        self._trabajo.paginas, parent=self):
            self.status.showMessage("Impresión cancelada.")
            self._iniciar_flujo_trabajo()
            return

        cantidad = self._trabajo.cantidad
        plural = "s" if cantidad != 1 else ""
        self.status.showMessage(
            f"{cantidad} página{plural} ({etiqueta_pags}) enviada{plural} a la impresora…")
        self._abrir_escaneo()

    def _abrir_escaneo(self):
        if self._trabajo is None:
            return
        self._cerrar_vista("_vista_escaneo")
        from modules.fase3_scan import VistaEscaneo
        self._vista_escaneo = VistaEscaneo(self._trabajo, parent=self)
        self._vista_escaneo.setWindowTitle("PDF Sign Assistant — Escanear páginas")
        self._vista_escaneo.resize(900, 660)
        self._vista_escaneo.completado.connect(self._on_escaneo_completado)
        self._vista_escaneo.cancelar.connect(self._on_escaneo_cancelado)
        self._vista_escaneo.show()

    def _on_escaneo_completado(self):
        self._cerrar_vista("_vista_escaneo")
        self._abrir_guardar()

    def _abrir_guardar(self):
        if self._trabajo is None:
            return
        self._cerrar_vista("_vista_guardar")
        from modules.fase_guardar import FaseGuardar
        self._vista_guardar = FaseGuardar(
            trabajo=self._trabajo, carpeta_firmados=CARPETA_FIRMADO, parent=self)
        self._vista_guardar.setWindowTitle("PDF Sign Assistant — Guardar documento")
        self._vista_guardar.resize(820, 640)
        self._vista_guardar.guardado_listo.connect(self._on_guardado_listo)
        self._vista_guardar.cancelado.connect(self._on_guardar_cancelado)
        self._vista_guardar.show()

    def _on_guardado_listo(self, ruta_final):
        self._cerrar_vista("_vista_guardar")
        trabajo = self._trabajo
        if trabajo is not None:
            log.info("Guardado %s con las páginas %s",
                     Path(ruta_final).name, trabajo.etiqueta_paginas())
            try:
                trabajo.ruta_pdf.unlink(missing_ok=True)
            except OSError:
                pass

        cantidad = trabajo.cantidad if trabajo else 0
        etiqueta_pags = trabajo.etiqueta_paginas() if trabajo else ""
        ruta_final = Path(ruta_final)

        self._desactivar_panel()
        self._agregar_item_guardado(ruta_final)

        plural = "s" if cantidad != 1 else ""
        self.status.showMessage(
            f"✅  Guardado: {ruta_final.name} ({cantidad} página{plural})")
        QMessageBox.information(
            self, "¡Listo!",
            f"Documento guardado:\n{ruta_final}\n\n"
            f"Página{plural} firmada{plural}: {etiqueta_pags}")

    def _on_guardar_cancelado(self):
        self._cerrar_vista("_vista_guardar")
        self._abrir_escaneo()

    def _on_escaneo_cancelado(self):
        self._cerrar_vista("_vista_escaneo")
        self._iniciar_flujo_trabajo()

    def _on_preview_cancelado(self):
        self._cerrar_vista("_vista_preview")
        self.status.showMessage("Vista de páginas cerrada.")

    # ── Reabrir guardado ──────────────────────────────────────────────────
    def _reabrir_desde_boton(self):
        item = self._item_seleccionado()
        if item:
            self._reabrir_guardado(item)

    def _reabrir_guardado(self, item: ItemGuardado):
        if self._trabajo is not None:
            QMessageBox.information(self, "PDF en proceso",
                                    "Cancelá el trabajo actual antes de abrir otro.")
            return
        ruta = item.ruta
        if not ruta.exists():
            QMessageBox.warning(self, "Archivo no encontrado",
                                f"El archivo ya no existe:\n{ruta}")
            self._recargar_guardados()
            return

        total_paginas = self._validar_pdf(ruta)
        if total_paginas is None:
            return

        copia = CARPETA_TRABAJO / f"reedit_{ruta.name}"
        try:
            shutil.copy2(ruta, copia)
        except OSError as e:
            QMessageBox.critical(self, "Error al copiar", str(e))
            return

        self._activar_pdf(copia, total_paginas)

        # Si el documento ya fue firmado por la app, proponemos de entrada
        # las mismas páginas: re-editar casi siempre es corregir esas hojas.
        from modules.fase_guardar import leer_paginas_firmadas
        previas = leer_paginas_firmadas(ruta)
        if previas and self._trabajo is not None:
            self._trabajo.set_paginas(previas)
            self.status.showMessage(
                f"Re-editando: {ruta.name}  ·  ya venía firmado en "
                f"{self._trabajo.etiqueta_paginas()}")
        else:
            self.status.showMessage(f"Re-editando: {ruta.name}")

    # ── Enviar correo ─────────────────────────────────────────────────────
    def _enviar_correo(self):
        item = self._item_seleccionado()
        if not item:
            return
        if not item.ruta.exists():
            QMessageBox.warning(self, "Archivo no encontrado",
                                f"No se encontró:\n{item.ruta}")
            self._recargar_guardados()
            return
        try:
            from modules.fase4_email import enviar_documento
        except ImportError as e:
            QMessageBox.critical(self, "Error de módulo", str(e))
            return

        # Las páginas firmadas quedan registradas en los metadatos del PDF
        # al guardarlo. Antes se mandaba [0] fijo y el resumen decía
        # "página 1" sin importar cuáles se hubieran firmado.
        from modules.fase_guardar import leer_paginas_firmadas
        paginas = leer_paginas_firmadas(item.ruta)

        enviar_documento(
            pdf_firmado=item.ruta,
            carpeta_firmados=CARPETA_FIRMADO,
            config=self.config,
            paginas=paginas,
            nombre_doc=item.ruta.stem,
            parent=self,
        )
        self.status.showMessage(f"Flujo de envío iniciado: {item.ruta.name}")

    # ── Abrir carpeta de firmados ─────────────────────────────────────────
    def _abrir_carpeta_firmados(self):
        CARPETA_FIRMADO.mkdir(parents=True, exist_ok=True)
        abrir_en_sistema(CARPETA_FIRMADO)
        self.status.showMessage(f"Carpeta abierta: {CARPETA_FIRMADO}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Escalado nítido en monitores con DPI alto (Windows al 125/150 %).
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NOMBRE)
    app.setApplicationVersion(__version__)

    icono = BASE_DIR / "assets" / "icon.png"
    if icono.is_file():
        app.setWindowIcon(QIcon(str(icono)))

    # El .exe se compila con console=False: sin log a archivo, cualquier
    # error en la máquina del usuario se perdía sin dejar rastro.
    archivo_log = configurar_logging()

    # Sin esto, una excepción no atrapada mata la app en silencio: el .exe
    # se compila con console=False y no hay dónde imprimir el traceback.
    instalar_manejador_errores(
        version=__version__,
        ruta_log=archivo_log,
        mostrar_dialogo=lambda msg: QMessageBox.critical(
            None, "Error inesperado", msg),
    )

    log.info("── %s v%s iniciado ──", APP_NOMBRE, __version__)
    log.info("Datos en %s", CONFIG_PATH.parent)
    log.info("Documentos firmados en %s", CARPETA_FIRMADO)
    log.info("Log en %s", archivo_log)

    huerfanos = limpiar_trabajos_huerfanos()
    if huerfanos:
        log.info("Limpiadas %d copias de trabajo viejas", huerfanos)

    config = cargar_config()
    apply_theme(app, config.get("tema", "light"))

    ventana = VentanaPrincipal()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
