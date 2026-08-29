"""
PDF Sign Assistant — main.py
============================================================
La ventana principal es un contenedor de herramientas.

  BarraLateral            menú permanente (modules/navegacion.py)
  PantallaInicio          el launcher, con una tarjeta por herramienta
  Herramienta "Firmar"    el flujo completo, que vive en esta ventana
  Herramienta "Escanear"  modules/herramienta_escaneo.py

Flujo de la herramienta de firma (el de siempre):
  1. Abrir PDF → se copia a la carpeta de trabajo.
  2. Panel del PDF activo (elegir páginas / cancelar).
  3. fase1_preview → fase2_print → fase3_scan → fase_guardar
  4. Al confirmar, el documento se suma a la lista de guardados.
  5. Doble clic en un guardado → lo reabre para re-editar.
  6. Seleccionarlo → habilita Editar y Enviar por correo.

Atajos de teclado:
  Ctrl+0  inicio             Ctrl+O  abrir PDF
  Ctrl+1  firmar un PDF      Ctrl+E  enviar por correo
  Ctrl+2  escanear a PDF     Ctrl+D  alternar tema
  Ctrl+F  buscar             F5      recargar la lista
  Enter   editar el documento seleccionado

Sin emojis
----------
Toda la iconografía sale de modules/iconos.py, que dibuja SVG. Los
emojis dependían de que la fuente instalada tuviera el glifo, y en
Windows eso fallaba de forma distinta en cada máquina: ⚙ se veía, 👁
salía como una raya y 🌙 como un punto.

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
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
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

from modules import iconos
from modules.errores import instalar as instalar_manejador_errores
from modules.fase1_preview import VistaPrevisualizacion
from modules.navegacion import CATALOGO, INICIO, BarraLateral, PantallaInicio
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
from modules.theme import BREAKPOINT, SIZE, SPACE, THEME, apply_theme, current_mode
from modules.trabajo import TrabajoFirma
from modules.ui import (
    BarraSuperior,
    Buscador,
    FilaAdaptable,
    abrir_en_sistema,
    boton,
    etiqueta,
    icono_label,
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
    panel, lay = tarjeta(padding=SPACE["lg"], spacing=SPACE["md"])
    panel.setObjectName("panelActivo")

    fila_info = QHBoxLayout()
    fila_info.setSpacing(SPACE["md"])

    icono = icono_label("documento-texto", SIZE["icono_md"], color="primary")
    fila_info.addWidget(icono, 0, Qt.AlignmentFlag.AlignTop)

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
    acciones.agregar(boton("Elegir páginas", icono="flecha-der", min_w=180,
                           height=SIZE["btn_lg"], on_click=on_trabajar))
    acciones.agregar_stretch()
    acciones.agregar(boton("Cancelar", variant="ghost", icono="cerrar",
                           height=SIZE["btn_lg"], on_click=on_cancelar))
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
        self.setSizeHint(QSize(0, 58))
        self.setToolTip(str(ruta))


class _DelegadoDocumento(QStyledItemDelegate):
    """Dibuja cada fila con jerarquía: icono, nombre en primer plano y
    fecha atenuada debajo. Con el texto por defecto de QListWidget ambas
    líneas salían con el mismo peso y tamaño."""

    ICONO = 18
    SANGRIA = 34        # ancho reservado al icono, incluido su margen

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

        painter.save()

        pm = iconos.pixmap("documento-firmado", self.ICONO, color="primary")
        painter.drawPixmap(
            rect.left(),
            rect.top() + (rect.height() - self.ICONO) // 2,
            pm)

        texto = rect.adjusted(self.SANGRIA, 0, 0, 0)
        mitad = texto.height() // 2

        fuente = QFont(opt.font)
        fuente.setWeight(QFont.Weight.DemiBold)
        painter.setFont(fuente)
        painter.setPen(QColor(THEME["text"]))
        metricas = QFontMetrics(fuente)
        painter.drawText(
            QRect(texto.left(), texto.top(), texto.width(), mitad),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metricas.elidedText(nombre, Qt.TextElideMode.ElideMiddle, texto.width()),
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
            QRect(texto.left(), texto.top() + mitad, texto.width(), mitad),
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
        self.setMinimumSize(520, 460)
        self.resize(1100, 720)

        self.config = cargar_config()
        # Todo el estado del trabajo en curso vive en TrabajoFirma
        self._trabajo: TrabajoFirma | None = None
        self._vista_preview = None
        self._vista_escaneo = None
        self._vista_guardar = None
        self._herramienta_escaneo = None      # se crea al usarla por primera vez
        self._paginas: dict[str, QWidget] = {}
        self._actual = INICIO

        self._worker_update = None
        self._build_ui()
        self._registrar_atajos()
        self._recargar_guardados()
        self._vigilar_carpeta()
        self._ir_a(INICIO)

        # Comprobación diferida: que la ventana abra primero. Buscar
        # actualizaciones nunca debe retrasar el arranque.
        QTimer.singleShot(3000, self._comprobar_actualizaciones_auto)

    # ── Cierre de la app ──────────────────────────────────────────────────
    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        """Limpia las carpetas temporales y cierra las vistas abiertas."""
        try:
            from modules.fase4_email import limpiar_temp_al_salir
            limpiar_temp_al_salir(CARPETA_FIRMADO)
        except Exception:
            pass
        if self._herramienta_escaneo is not None:
            self._herramienta_escaneo.limpiar_temporales()
        self._cerrar_vistas_abiertas()
        super().closeEvent(event)

    # ── Construcción de la ventana ────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("pantalla")
        self.setCentralWidget(central)

        raiz = QHBoxLayout(central)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        self.barra_lateral = BarraLateral(__version__)
        self.barra_lateral.herramienta_elegida.connect(self._ir_a)
        self.barra_lateral.accion.connect(self._accion_lateral)
        raiz.addWidget(self.barra_lateral)

        self.paginas = QStackedWidget()
        raiz.addWidget(self.paginas, 1)

        self.pantalla_inicio = PantallaInicio()
        self.pantalla_inicio.herramienta_elegida.connect(self._ir_a)
        self.pantalla_inicio.abrir_carpeta.connect(self._abrir_carpeta_firmados)
        self.pantalla_inicio.abrir_documento.connect(abrir_en_sistema)
        self._registrar_pagina(INICIO, self.pantalla_inicio)

        self._registrar_pagina("firmar", self._construir_pagina_firmar())

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Listo — elegí una herramienta para empezar.")

    def _registrar_pagina(self, clave: str, widget: QWidget) -> QWidget:
        self._paginas[clave] = widget
        self.paginas.addWidget(widget)
        return widget

    # ── Navegación ────────────────────────────────────────────────────────
    def _ir_a(self, destino: str) -> None:
        pagina = self._paginas.get(destino) or self._crear_pagina(destino)
        if pagina is None:
            return
        self._actual = destino
        self.paginas.setCurrentWidget(pagina)
        self.barra_lateral.set_activa(destino)
        if destino == INICIO:
            self._actualizar_inicio()

    def _crear_pagina(self, destino: str) -> QWidget | None:
        """Construye una herramienta la primera vez que se abre.

        Se hace tarde y no en el arranque: la de escaneo consulta el
        escáner al armarse, y las dos importan PyMuPDF y pypdf. Retrasar
        la ventana por algo que quizás nunca se use no tiene sentido.
        """
        if destino == "escanear":
            from modules.herramienta_escaneo import VistaEscanearAPdf

            vista = VistaEscanearAPdf(
                CARPETA_FIRMADO,
                calidad_inicial=self.config.get("calidad_pdf"),
                limite_mb=self.config.get("limite_correo_mb", 20))
            self._herramienta_escaneo = vista

        elif destino == "unir":
            from modules.herramienta_unir import VistaUnirDividirPdf

            vista = VistaUnirDividirPdf(CARPETA_FIRMADO)

        else:
            return None

        vista.volver.connect(lambda: self._ir_a(INICIO))
        vista.documento_guardado.connect(self._on_pdf_escaneado)
        return self._registrar_pagina(destino, vista)

    def _accion_lateral(self, clave: str) -> None:
        if clave == "tema":
            self._toggle_tema()
        elif clave == "ajustes":
            self._abrir_ajustes()
        elif clave == "carpeta":
            self._abrir_carpeta_firmados()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Con la ventana angosta, 236 px de barra lateral son un tercio del
        # ancho útil: se colapsa a la tira de iconos.
        self.barra_lateral.set_compacta(self.width() < BREAKPOINT["md"])

    # ── Herramienta: firmar un PDF ────────────────────────────────────────
    def _construir_pagina_firmar(self) -> QWidget:
        pagina = QWidget()
        raiz = QVBoxLayout(pagina)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        cabecera = BarraSuperior("Firmar un PDF", icono_nombre="firma")
        self.btn_abrir = boton("Abrir PDF", icono="mas", min_w=140,
                               tooltip="Abrir un PDF para trabajar (Ctrl+O)",
                               on_click=self.abrir_pdf)
        cabecera.agregar(self.btn_abrir)
        raiz.addWidget(cabecera)

        cuerpo = QWidget()
        lay = QVBoxLayout(cuerpo)
        lay.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["md"])
        lay.setSpacing(SPACE["md"])

        # Panel del PDF activo (oculto mientras no hay ninguno)
        self.panel_activo_container = QWidget()
        self.panel_activo_container.setVisible(False)
        self._lay_panel = QVBoxLayout(self.panel_activo_container)
        self._lay_panel.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.panel_activo_container)

        lay.addWidget(self._construir_encabezado_lista())
        lay.addWidget(self._construir_lista(), 1)
        lay.addWidget(self._construir_acciones())

        raiz.addWidget(cuerpo, 1)
        return pagina

    def _construir_encabezado_lista(self) -> QWidget:
        fila = QWidget()
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE["sm"])

        lay.addWidget(etiqueta("DOCUMENTOS FIRMADOS", rol="seccion"))
        lay.addStretch()

        self.input_buscar = Buscador("Buscar por nombre…")
        self.input_buscar.setMaximumWidth(240)
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
        lay_v.addWidget(icono_label("documento-firmado", 44, color="text_faint"),
                        0, Qt.AlignmentFlag.AlignCenter)
        lay_v.addSpacing(SPACE["sm"])
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

        self.btn_reabrir = boton("Editar seleccionado", variant="secondary",
                                 icono="lapiz", enabled=False,
                                 tooltip="Volver a firmar (Enter)",
                                 on_click=self._reabrir_desde_boton)
        acciones.agregar(self.btn_reabrir)

        self.btn_email = boton("Enviar por correo", variant="secondary",
                               icono="sobre", enabled=False,
                               tooltip="Enviar el documento (Ctrl+E)",
                               on_click=self._enviar_correo)
        acciones.agregar(self.btn_email)
        acciones.agregar_stretch()

        self.btn_carpeta = boton("Abrir carpeta", variant="ghost",
                                 icono="carpeta-abierta",
                                 tooltip=str(CARPETA_FIRMADO),
                                 on_click=self._abrir_carpeta_firmados)
        acciones.agregar(self.btn_carpeta)
        return acciones

    def _registrar_atajos(self):
        pagina_firmar = self._paginas["firmar"]

        # Navegación entre herramientas
        atajos_nav = [("Ctrl+0", INICIO)]
        for i, herramienta in enumerate(CATALOGO, start=1):
            atajos_nav.append((f"Ctrl+{i}", herramienta.id))
        for secuencia, destino in atajos_nav:
            QShortcut(QKeySequence(secuencia), self,
                      activated=lambda d=destino: self._ir_a(d))

        # Globales
        for secuencia, funcion in (
            ("Ctrl+O", self._abrir_pdf_desde_atajo),
            ("Ctrl+D", self._toggle_tema),
        ):
            QShortcut(QKeySequence(secuencia), self, activated=funcion)

        # Sólo dentro de la herramienta de firma: si fueran globales, Enter
        # se comería el de la herramienta de escaneo.
        for secuencia, funcion in (
            ("Ctrl+E", self._enviar_correo),
            ("Ctrl+F", lambda: self.input_buscar.setFocus()),
            ("F5", self._recargar_guardados),
            ("Return", self._reabrir_desde_boton),
        ):
            QShortcut(QKeySequence(secuencia), pagina_firmar, activated=funcion,
                      context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def _abrir_pdf_desde_atajo(self):
        self._ir_a("firmar")
        self.abrir_pdf()

    # ── Tema ──────────────────────────────────────────────────────────────
    def _toggle_tema(self):
        nuevo = "dark" if current_mode() == "light" else "light"
        apply_theme(QApplication.instance(), nuevo)
        self.barra_lateral.sincronizar_tema()

        self.config["tema"] = nuevo
        try:
            guardar_config(self.config, CONFIG_PATH)
        except OSError:
            pass
        self.status.showMessage(
            f"Tema {'oscuro' if nuevo == 'dark' else 'claro'} activado.")

    # ── Lista de guardados ────────────────────────────────────────────────
    def _recargar_guardados(self):
        """Relee la carpeta de firmados y reconstruye la lista.

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
        self._actualizar_inicio()

    def _actualizar_inicio(self):
        """Refresca los documentos recientes que muestra el launcher."""
        recientes = []
        for i in range(min(3, self.lista_guardados.count())):
            item = self.lista_guardados.item(i)
            recientes.append((item.ruta, item.data(ROL_FECHA) or ""))
        self.pantalla_inicio.set_recientes(recientes,
                                           self.lista_guardados.count())

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

    # ── Herramienta: escanear a PDF ───────────────────────────────────────
    def _on_pdf_escaneado(self, ruta: str):
        destino = Path(ruta)
        log.info("PDF armado desde el escáner: %s", destino.name)
        self.status.showMessage(f"Documento creado: {destino.name}")
        if destino.parent == CARPETA_FIRMADO:
            self._agregar_item_guardado(destino)

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
        self._ir_a("firmar")
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
            f"{cantidad} página{plural} ({etiqueta_pags}) "
            f"enviada{plural} a la impresora…")
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
            trabajo=self._trabajo, carpeta_firmados=CARPETA_FIRMADO, parent=self,
            calidad_inicial=self.config.get("calidad_pdf"),
            limite_mb=self.config.get("limite_correo_mb", 20))
        self._vista_guardar.calidad_elegida.connect(self._recordar_calidad)
        self._vista_guardar.setWindowTitle("PDF Sign Assistant — Guardar documento")
        self._vista_guardar.resize(820, 640)
        self._vista_guardar.guardado_listo.connect(self._on_guardado_listo)
        self._vista_guardar.cancelado.connect(self._on_guardar_cancelado)
        self._vista_guardar.show()

    def _recordar_calidad(self, clave: str):
        """La calidad elegida se recuerda: quien la baja una vez suele
        necesitarla siempre (su correo tiene el mismo límite mañana)."""
        if not clave or self.config.get("calidad_pdf") == clave:
            return
        self.config["calidad_pdf"] = clave
        try:
            guardar_config(self.config, CONFIG_PATH)
        except OSError:
            pass

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
            f"Guardado: {ruta_final.name} ({cantidad} página{plural})")
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
    else:
        # Sin archivo de icono, mejor el dibujado que el genérico de Qt.
        app.setWindowIcon(QIcon(iconos.icono_app(256)))

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
