# PDF Sign Assistant

> Aplicación de escritorio en Python + PyQt6 para automatizar el flujo completo de firma de documentos legales — diseñada para usuarios no técnicos con una interfaz clara, guiada y con soporte de modo claro/oscuro.

---

## Descripción

**PDF Sign Assistant** simplifica el proceso de firmar documentos PDF físicamente y producir una copia digital actualizada. En lugar de editar PDFs manualmente o gestionar imágenes escaneadas sueltas, la app guía al usuario paso a paso: previsualizar páginas → imprimir → escanear → incrustar → guardar → enviar.

Toda la interacción ocurre desde una sola ventana con controles grandes, bien etiquetados y retroalimentación de estado en tiempo real.

---

## Funcionalidades

- 📄 **Vista previa en cuadrícula** — visualizá todas las páginas del PDF antes de elegir cuál firmar
- 🖨️ **Impresión directa** — envía la página seleccionada a la impresora automáticamente
- 🖼️ **Integración con escáner** — cargá o capturá la imagen escaneada de la página firmada
- 🔄 **Reemplazo de página** — incrusta la firma escaneada de vuelta en el PDF original
- 💾 **Lista de trabajos guardados** — historial de documentos procesados con fecha y hora; permite re-editar
- ✉️ **Envío por correo** — abre tu cliente de correo con destinatario/asunto listos y una carpeta temporal con el PDF adjuntable
- ⚙️ **Panel de ajustes** — configurá el correo emisor (servidor, puerto, credenciales) desde la UI, sin tocar archivos de configuración
- 🌙 **Modo claro y oscuro** — alternás con un clic; se aplica a toda la interfaz en tiempo real y queda recordado entre sesiones
- 📐 **Interfaz adaptable** — las pantallas reacomodan columnas y apilan paneles cuando la ventana es angosta; todo entra desde 460 px de ancho
- ⌨️ **Atajos de teclado** — flujo completo sin mouse (ver tabla más abajo)
- 🔎 **Búsqueda en guardados** — filtrá el historial por nombre a medida que escribís
- 🔒 **Cancelación segura** — cancelá en cualquier etapa sin corromper el archivo original

---

## Flujo de trabajo

```
Abrir PDF  →  Vista previa  →  Imprimir página  →  Escanear página firmada  →  Guardar PDF  →  Enviar
```

| Paso | Módulo | Descripción |
|------|--------|-------------|
| 1 | `main.py` | Abrir un PDF y cargarlo en la sesión de trabajo |
| 2 | `fase1_preview.py` | Cuadrícula desplazable de miniaturas; selección de la página objetivo |
| 3 | `fase2_print.py` | Envío de la página seleccionada a la impresora del sistema |
| 4 | `fase3_scan.py` | Carga de la imagen escaneada/fotografiada de la página firmada |
| 5 | `fase_guardar.py` | Vista previa del resultado, confirmación y guardado del PDF firmado |
| 6 | `fase4_email.py` | Flujo de envío: carpeta temporal + apertura del cliente de correo |

---

## Estructura del proyecto

```
pdf-sign-assistant/
├── main.py                  # Punto de entrada · ventana principal · orquestación del flujo
├── config.json              # Configuración local (NO versionada — la escribe Ajustes)
├── config.example.json      # Plantilla de configuración
├── config.example.env       # Plantilla de variables de entorno
├── requirements.txt         # Dependencias de Python
├── pdf_sign_assistant.spec  # Configuración de PyInstaller para generar el .exe
├── pdfs_trabajo/            # Copias de trabajo temporales (auto-creado, gitignored)
├── pdfs_firmados/           # Documentos firmados finales (auto-creado, gitignored)
│   └── _envio_temp/         # Carpeta temporal para adjuntar en correos (se borra al cerrar la app)
└── modules/
    ├── __init__.py
    ├── setup.py             # Rutas compatibles con PyInstaller + carga/guardado de config
    ├── theme.py             # Sistema de diseño: paletas, tokens (espaciado/radios/tipografía), stylesheet
    ├── ui.py                # Kit de componentes compartidos (botones, tarjetas, barras, contenedores responsive)
    ├── settings.py          # Diálogo de ajustes de correo emisor (SMTP, credenciales)
    ├── fase1_preview.py     # Cuadrícula de miniaturas y selección de página
    ├── fase2_print.py       # Integración con la impresora del sistema
    ├── fase3_scan.py        # Carga de imagen y vista previa del escaneo
    ├── fase_guardar.py      # Lógica de reemplazo de página y guardado del PDF
    └── fase4_email.py       # Flujo de envío: carpeta temporal + cliente de correo
```

---

## Flujo de envío por correo

El envío **no usa SMTP directo** — en cambio abre tu cliente de correo habitual (Outlook, Gmail, Thunderbird, etc.) con los datos ya cargados, y te muestra el PDF listo para arrastrar al adjunto.

1. Seleccioná un documento firmado en la lista y pulsá **✉️ Enviar por correo**
2. Completá el destinatario y el asunto en el diálogo
3. Pulsá **✉️ Abrir correo y carpeta** — se abren simultáneamente:
   - El **Explorador de archivos** mostrando `pdfs_firmados/_envio_temp/` con solo ese PDF
   - Tu **cliente de correo** (o navegador) con destinatario y asunto ya listos
4. Arrastrá el PDF al correo y enviá normalmente

La carpeta `_envio_temp/` se borra **al cerrar la app** y también **al iniciarla**, por si la sesión anterior terminó de forma abrupta.

---

## Atajos de teclado

| Atajo | Acción |
|-------|--------|
| `Ctrl+O` | Abrir un PDF |
| `Ctrl+E` | Enviar por correo el documento seleccionado |
| `Ctrl+F` | Buscar en la lista de guardados |
| `Ctrl+D` | Alternar tema claro / oscuro |
| `F5` | Recargar la lista de documentos |
| `Enter` | Editar el documento seleccionado |

Dentro de la vista de páginas: `←` `→` `↑` `↓` para moverte por la cuadrícula,
`Inicio`/`Fin` para saltar a la primera o última página, `Enter` (o doble clic)
para confirmar y `Esc` para salir. En escaneo y guardado: `Esc` vuelve atrás y
`Enter` confirma.

---

## Requisitos previos

- **Python** 3.10 o superior
- **Windows** para imprimir y escanear: la impresión usa GDI (`StretchDIBits`) y el escaneo usa WIA, ambos vía `pywin32`.
  El resto de la app (abrir, previsualizar, reemplazar página, guardar, enviar) funciona en cualquier sistema.
- **Escáner compatible** *(opcional — también se pueden cargar imágenes desde disco o arrastrarlas a la ventana)*:
  - Windows: WIA (integrado, compatible con HP LaserJet MFP)

> No hace falta Poppler ni `pdf2image`: el render lo hace **PyMuPDF** directamente.

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/CrazyK-oss/pdf-sign-assistant.git
cd pdf-sign-assistant

# 2. Crear entorno virtual
python -m venv venv

# 3. Activarlo
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux / macOS

# 4. Instalar dependencias
pip install -r requirements.txt
```

---

## Configuración

### Opción A — Panel de Ajustes (recomendado)

Abrí la app y hacé clic en el botón **⚙** del header. Desde ahí podés configurar:
- Proveedor SMTP (Gmail, Outlook, Yahoo, Zoho o Personalizado)
- Correo emisor y contraseña de aplicación
- Servidor y puerto SMTP

Los cambios se guardan en `config.json` (escritura atómica: se escribe un temporal y recién ahí se reemplaza el archivo).

### Opción B — Copiar la plantilla

```bash
cp config.example.json config.json     # Windows: copy config.example.json config.json
```

```json
{
    "email_user": "tucorreo@dominio.com",
    "email_password": "",
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "tema": "light"
}
```

Si `config.json` no existe, la app arranca igual con los valores por defecto.

### Sobre las credenciales

`config.json` **no se versiona** (está en `.gitignore`) porque el diálogo de Ajustes escribe ahí lo que cargues.

> ⚠️ La contraseña se guarda **en texto plano** y hoy **ningún flujo la usa**: el envío abre tu cliente
> de correo por `mailto:` en vez de hablar SMTP. Podés dejar el campo vacío sin perder ninguna función.
> Si más adelante se implementa el envío SMTP directo, conviene mover el secreto a `.env`
> (ya soportado vía `python-dotenv`) o al almacén de credenciales del sistema.

---

## Ejecutar la app

```bash
python main.py
```

La app crea automáticamente las carpetas `pdfs_trabajo/` y `pdfs_firmados/` al iniciarse.

---

## Generar ejecutable (.exe)

```bash
# Con el venv activo:
pip install pyinstaller
pyinstaller pdf_sign_assistant.spec
```

El ejecutable se genera en `dist/PDF Sign Assistant/`. Distribuid **siempre la carpeta completa**, nunca solo el `.exe`.

> **Nota:** Si PyInstaller no encuentra `python3XX.dll`, el `.spec` incluye lógica para localizarla automáticamente usando `sys.base_exec_prefix` (funciona correctamente dentro de entornos virtuales).

---

## Dependencias

| Paquete | Propósito |
|---------|-----------|
| `PyQt6` | Framework de UI de escritorio |
| `pymupdf` | Parseo y renderizado de PDFs |
| `Pillow` | Procesamiento y conversión de imágenes |
| `img2pdf` | Conversión de imagen a PDF |
| `pypdf` | Manipulación de PDFs (reemplazo de páginas) |
| `reportlab` | Motor principal de conversión imagen → PDF |
| `pywin32` | Impresión GDI y escáner WIA en Windows (`sys_platform == "win32"`) |
| `python-dotenv` | Carga de archivos `.env` |

---

## Changelog

### v0.6 — Rendimiento, estandarización visual y responsive *(actual)*

**Rendimiento**
- **Impresión ~8x más rápida** (`fase2_print.py`): la conversión RGB→BGR se hacía con un bucle Python byte a byte sobre ~26 MB (≈1,2 s por página con la UI congelada). Ahora usa asignación por slices, que corre en C (≈0,15 s)
- **La impresión ya no bloquea la interfaz**: render y envío a la impresora corren en un `QThread` con diálogo de progreso
- **El printer DC se abre una sola vez** (antes se abría, se cerraba para leer capacidades y se volvía a abrir)
- **Miniaturas**: las tarjetas se crean apenas se conoce el total de páginas y se rellenan a medida que llegan los renders; redimensionar la ventana reacomoda el grid **sin volver a leer el PDF** (~80 ms con 126 páginas)
- **Un solo `stat()` por archivo** al listar los documentos guardados

**Correcciones**
- **Crash latente por hilos** (`fase1_preview.py`): el worker construía `QPixmap` fuera del hilo de GUI, algo que Qt no permite. Ahora emite `QImage` y la conversión ocurre en el hilo principal
- **Grid corrupto al redimensionar**: el número de columnas se recalculaba en cada miniatura que llegaba, así que cambiar el tamaño a mitad de carga dejaba huecos y tarjetas superpuestas
- **Bordes fantasma en todas las tarjetas**: los paneles declaraban `QFrame { border… }` y, como `QLabel` hereda de `QFrame`, cada etiqueta hija dibujaba su propio recuadro
- **Fondos opacos sobre las tarjetas**: la regla base pintaba `background-color` en `QWidget` genérico, tapando el fondo de los contenedores
- **Ventanas de fase dibujadas como widgets hijos**: a `VistaEscaneo` le faltaba el flag `Qt.Window` y se renderizaba encima de la ventana principal
- **img2pdf relanzaba la app** (`fase_guardar.py`): el subproceso se lanzaba con `sys.executable -c`, que dentro de un `.exe` de PyInstaller **es la propia aplicación**. En modo congelado ahora se salta ese motor
- **`logging.basicConfig()` al importar**: un módulo reconfiguraba el logger raíz de toda la app en `DEBUG`
- **Cierre bloqueante en escaneo**: `closeEvent` esperaba al worker WIA, que puede estar mostrando un diálogo modal del sistema
- **Hueco muerto** entre el encabezado y la lista en la ventana principal
- **Escritura de `config.json` no atómica** y sin tolerancia a archivos corruptos

**Interfaz**
- **Sistema de diseño real**: `theme.py` pasa a ser la única fuente de verdad (paletas + tokens de espaciado, radios, tipografía y tamaños) y se suma `modules/ui.py` con los componentes compartidos
- **Modo oscuro completo**: las fases 1, 3, 4 y guardado tenían sus propios colores fijos y quedaban en claro aunque la app estuviera en oscuro. `fase4_email.py` incluso duplicaba la paleta entera
- **QPalette sincronizada** con el tema, para que los diálogos nativos (archivos, mensajes, impresión) también respeten el modo oscuro
- **El tema se recuerda** entre sesiones y las ventanas abiertas se repintan en caliente
- **Lista de guardados con jerarquía**: nombre y fecha con peso y tamaño distintos, vía delegado propio
- **Búsqueda** en el historial y **recarga automática** cuando la carpeta cambia desde afuera
- **Validación en vivo** del nombre de archivo y del correo destinatario
- **Aviso antes de copiar** si el PDF está dañado o protegido con contraseña

**Responsive**
- Cuadrícula de páginas con columnas y ancho de tarjeta calculados según el espacio disponible (con *debounce* al redimensionar)
- Los paneles de escaneo y las filas de botones se apilan en vertical en ventanas angostas
- Las pantallas largas van dentro de un scroll, así no se recortan en monitores bajos o con escalado de fuente grande
- Alturas mínimas en vez de fijas y escalado consciente de DPI alto

**Mantenimiento**
- `exchangelib` y `watchdog` eliminados de `requirements.txt`: ningún módulo los importaba y `exchangelib` arrastraba `lxml`, `dnspython` y compañía al bundle
- `pywin32` marcado como dependencia sólo de Windows
- `config.json` fuera del control de versiones (puede contener credenciales); se versiona `config.example.json`
- Lógica de configuración y de apertura de carpetas unificada (estaba duplicada entre `main.py`, `settings.py` y `fase4_email.py`)

### v0.5 — Flujo de envío con carpeta temporal *(actual)*
- **Nuevo flujo de envío** (`fase4_email.py`): copia el PDF a `pdfs_firmados/_envio_temp/` y abre el cliente de correo y el Explorador simultáneamente
- **Limpieza automática** de `_envio_temp/` a los 30 minutos vía hilo daemon
- **Limpieza al inicio** de la app: si quedó una carpeta temporal de una sesión anterior, se elimina antes de mostrar la ventana
- **Fix crítico impresión** (`fase2_print.py`): reemplazado el flujo `CreateBitmap/SelectObject` por `ImageWin.Dib.draw()` para eliminar el error `Select bitmap object failed`

### v0.4 — Rediseño UI/UX + Modo Oscuro
- **Sistema de diseño unificado** (`modules/theme.py`) con paletas `LIGHT` y `DARK` y stylesheet centralizado
- **Toggle claro/oscuro** en el header — se aplica a toda la interfaz en tiempo real
- **Fix crítico:** eliminado `QFormLayout.removeRow()` en `settings.py` que causaba crash al abrir el diálogo de ajustes
- **Fix:** fuentes definidas con `font_pt()` (siempre `>= 1`) para eliminar el warning `QFont::setPointSize: Point size <= 0`
- Rediseño visual completo: nuevos tokens de color, bordes, radios, scrollbars y estados hover/focus
- Botones con jerarquía clara: primario / secundario / ghost

### v0.3 — Panel de Ajustes de Correo
- Nuevo módulo `modules/settings.py` con `DialogoAjustes`
- Presets SMTP para Gmail, Outlook, Yahoo y Zoho
- Toggle mostrar/ocultar contraseña
- Validación de campos antes de guardar
- Persistencia directa en `config.json`

### v0.2 — Configuración PyInstaller
- `pdf_sign_assistant.spec` para generar ejecutables Windows
- Detección automática de `python3XX.dll` usando `sys.base_exec_prefix` (venv-safe)
- Bundle de DLLs de pywin32 y datos de PyQt6/fitz

### v0.1 — Flujo base
- Flujo completo: abrir → previsualizar → imprimir → escanear → guardar → enviar
- Lista de trabajos guardados con re-edición
- Cancelación segura en cualquier etapa

---

## Roadmap

- [ ] **Firma de múltiples páginas** — seleccionar y procesar varias páginas en una sola sesión
- [ ] **Procesamiento por lotes** — poner en cola varios PDFs y firmarlos secuencialmente
- [ ] **Firma digital criptográfica** — incrustar firmas digitales sin necesidad de imprimir
- [ ] **Exportar como ZIP** — empaquetar el PDF firmado junto con sus imágenes escaneadas
- [ ] **Soporte macOS** — integración nativa con impresoras y escáneres vía CUPS / ImageCapture
- [x] ~~**Persistencia del tema** — recordar la preferencia de tema claro/oscuro entre sesiones~~ *(v0.6)*

---

## Notas técnicas

- Solo puede haber **un PDF en proceso** a la vez; el botón "Abrir PDF" se deshabilita hasta que la sesión actual se cierre o complete.
- Las copias de trabajo se guardan en `pdfs_trabajo/` y se limpian automáticamente al guardar o cancelar.
- Los documentos firmados se persisten en `pdfs_firmados/` y aparecen en la ventana principal con su fecha de modificación.
- La carpeta `pdfs_firmados/_envio_temp/` es estrictamente temporal — no guardes archivos importantes ahí.
- Hacer doble clic en un documento guardado lo reabre para re-editar sin modificar el original.
- Todos los errores se muestran como diálogos amigables; los tracebacks detallados se imprimen en consola para depuración.
- La conversión imagen → PDF intenta tres motores en orden: **reportlab** → **img2pdf** (en subproceso aislado, porque puede crashear a nivel de extensión C) → **Pillow**.
- La ventana principal vigila `pdfs_firmados/` con `QFileSystemWatcher`: si agregás o borrás archivos desde el Explorador, la lista se actualiza sola.
