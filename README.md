# PDF Sign Assistant

> Caja de herramientas de escritorio en Python + PyQt6 para trabajar con PDFs: firmarlos a mano sin perder el original y armar documentos nuevos desde el escáner — diseñada para usuarios no técnicos, con una interfaz clara, guiada y con modo claro/oscuro.

<p align="center">
  <img src="assets/icon.png" width="120" alt="PDF Sign Assistant">
</p>

---

## ⬇️ Descargar

**[Descargar la última versión](https://github.com/CrazyK-oss/pdf-sign-assistant/releases/latest)** · Windows 10 u 11

| Archivo | Para quién |
|---------|-----------|
| `PDFSignAssistant-X.Y.Z-Setup.exe` | **La mayoría.** No pide permisos de administrador y crea el acceso directo. |
| `PDFSignAssistant-X.Y.Z-portable.zip` | Sin instalar nada (por ejemplo, desde un pendrive). Descomprimir y ejecutar. |

### La primera vez, Windows va a advertirte

La aplicación **no está firmada digitalmente**, así que SmartScreen muestra
*"Windows protegió su PC"*. Es lo esperable en software sin certificado, no una
señal de que el archivo esté mal. Para continuar:

**Más información → Ejecutar de todas formas**

Si querés verificar la descarga, cada Release publica un `SHA256SUMS.txt`.

### Actualizaciones

Una vez instalada, **no hace falta volver a descargar nada**: la app consulta
una vez por día si hay versión nueva y te avisa. Si aceptás, descarga el
instalador, verifica su integridad y se actualiza sola — se cierra, se
actualiza y se vuelve a abrir.

Se puede desactivar en **⚙ Ajustes → Actualizaciones**, donde también está el
botón **Buscar ahora**.

> Nunca se instala nada sin tu confirmación: la comprobación es automática, la
> instalación no.

### Dónde quedan tus archivos

| Qué | Dónde |
|-----|-------|
| Documentos firmados | `Documentos\PDF Sign Assistant` |
| Configuración y logs | `%LOCALAPPDATA%\PDF Sign Assistant` |

Al desinstalar, **tus documentos no se borran**. Si venías de una versión
anterior que guardaba todo junto al ejecutable, la app mueve esos datos a las
carpetas nuevas la primera vez que arranca.

---

## Descripción

**PDF Sign Assistant** es un menú de herramientas para trabajar con PDFs sin
salir de tu máquina. Hoy trae dos:

| Herramienta | Para qué sirve |
|-------------|----------------|
| **Firmar un PDF** | Imprimí las páginas que hay que firmar, firmalas a mano, escaneálas y la app las reemplaza dentro del documento original. El PDF que sale es el mismo de siempre, con tu firma real encima |
| **Escanear a PDF** | Armá un documento nuevo página por página desde el escáner. Reordenalas, giralas, descartá la que salió mal y guardá el PDF terminado |

Todo pasa en la computadora del usuario: no hay servidor, ni cuenta, ni
subida de archivos a ningún lado.

Agregar una herramienta más es sumar una entrada a `CATALOGO`
(`modules/navegacion.py`) y registrar su widget: ni la barra lateral ni la
pantalla de inicio hay que tocarlas.

---

## Funcionalidades

- 🧰 **Menú de herramientas** — barra lateral permanente y pantalla de inicio con una tarjeta por herramienta; se colapsa a una tira de iconos cuando la ventana se angosta
- 🖨️ **Escanear a PDF** — armá un documento nuevo hoja por hoja: cada página aparece con su miniatura y se puede subir, bajar, girar o descartar antes de guardar
- 🎨 **Iconografía vectorial propia** — 49 iconos dibujados en SVG dentro del código, que se colorean con el tema. Ya no dependen de que la fuente del sistema tenga el emoji (`👁` salía como una raya y `🌙` como un punto, según la máquina)
- 📄 **Vista previa en cuadrícula** — visualizá todas las páginas del PDF antes de elegir cuáles firmar
- 🗂️ **Firma de varias páginas por sesión** — elegí 1, 3 o 20 páginas: se imprimen en un solo trabajo, se escanean en una cola y se reemplazan todas de una vez
- 🔍 **Vista previa grande** — doble clic en una página para verla completa y decidir con seguridad
- 🔄 **Rotación por página** — corregí escaneos al revés sin salir de la app ni tocar el archivo original
- 🖨️ **Impresión directa** — envía las páginas seleccionadas a la impresora en un único trabajo
- 🖼️ **Integración con escáner** — digitalizá cada hoja o cargá varias imágenes de una y se reparten solas entre las páginas pendientes
- 📌 **Reemplazo de páginas** — incrusta cada hoja firmada en su página correspondiente del PDF original
- 💾 **Lista de trabajos guardados** — historial de documentos procesados con fecha y hora; permite re-editar
- ✉️ **Envío por correo** — abre tu cliente de correo con destinatario/asunto listos y una carpeta temporal con el PDF adjuntable
- ⚙️ **Panel de ajustes** — configurá el correo emisor (servidor, puerto, credenciales) desde la UI, sin tocar archivos de configuración
- 🌙 **Modo claro y oscuro** — alternás con un clic; se aplica a toda la interfaz en tiempo real y queda recordado entre sesiones
- 📐 **Interfaz adaptable** — las pantallas reacomodan columnas y apilan paneles cuando la ventana es angosta; todo entra desde 460 px de ancho
- ⌨️ **Atajos de teclado** — flujo completo sin mouse (ver tabla más abajo)
- 🔎 **Búsqueda en guardados** — filtrá el historial por nombre a medida que escribís
- 🧾 **Registro en el propio PDF** — el documento guarda qué páginas se firmaron, así al reabrirlo o enviarlo el resumen es exacto
- 🔔 **Actualizador interno** — la app avisa cuando hay versión nueva y se actualiza sola, sin pasar por GitHub ni reinstalar a mano
- 📋 **Log en archivo** — `logs/pdf_sign_assistant.log` con rotación, para diagnosticar problemas en la PC del usuario
- 🔒 **Cancelación segura** — cancelá en cualquier etapa sin corromper el archivo original

---

## Flujo de trabajo

### Firmar un PDF

```
Abrir PDF  →  Elegir páginas  →  Imprimir  →  Escanear cada hoja firmada  →  Guardar PDF  →  Enviar
```

Se pueden firmar **varias páginas en una misma sesión**. La selección, las
imágenes de cada página y sus rotaciones viven en un único objeto
(`modules/trabajo.py`), así que volver atrás en cualquier paso conserva lo
que ya habías hecho.

| Paso | Módulo | Descripción |
|------|--------|-------------|
| 1 | `main.py` | Abrir un PDF y cargarlo en la sesión de trabajo |
| 2 | `fase1_preview.py` | Cuadrícula de miniaturas; selección múltiple y vista previa grande |
| 3 | `fase2_print.py` | Envío de todas las páginas elegidas en un solo trabajo de impresión |
| 4 | `fase3_scan.py` | Cola de escaneo: una imagen por página, con rotación y avisos de orientación |
| 5 | `fase_guardar.py` | Reemplazo de todas las páginas, metadatos y guardado del PDF firmado |
| 6 | `fase4_email.py` | Flujo de envío: carpeta temporal + apertura del cliente de correo |

### Escanear a PDF

```
Escanear hoja  →  (repetir)  →  Reordenar / girar / descartar  →  Guardar PDF
```

Es un flujo mucho más corto porque no hay documento original que respetar:
se van apilando páginas hasta que el documento está completo.

| Paso | Módulo | Descripción |
|------|--------|-------------|
| 1 | `escaner_qt.py` | Digitaliza una hoja a 300 DPI en un hilo aparte, sin congelar la ventana |
| 2 | `documento_escaneado.py` | Modelo de la lista de páginas: orden, rotación y altas/bajas (lógica pura, sin Qt) |
| 3 | `herramienta_escaneo.py` | La pantalla: miniaturas, vista previa y acciones por página |
| 4 | `imagen_pdf.py` | Cada imagen → PDF de una página; después se unen en el documento final |

También se pueden **arrastrar imágenes** a la ventana o importarlas desde el
disco, por si el escaneo ya estaba hecho.

---

## Estructura del proyecto

```
pdf-sign-assistant/
├── main.py                  # Punto de entrada · ventana principal · orquestación del flujo
├── LICENSE                  # MIT
├── assets/icon.ico          # Icono de la app y del instalador
├── installer/               # Script de Inno Setup (genera el Setup.exe)
├── tests/                   # Tests de lógica pura (corren en CI, sin Qt)
├── .github/workflows/       # CI en cada push · Release al crear un tag
├── config.json              # Configuración local (NO versionada — la escribe Ajustes)
├── config.example.json      # Plantilla de configuración
├── config.example.env       # Plantilla de variables de entorno
├── requirements.txt         # Dependencias de Python
├── pdf_sign_assistant.spec  # Configuración de PyInstaller para generar el .exe
│                            # (en ejecución, los datos NO se guardan acá:
│                            #  ver la tabla de "Dónde quedan tus archivos")
└── modules/
    ├── __init__.py
    │
    │   # ── Base visual ───────────────────────────────────────────────
    ├── theme.py             # Sistema de diseño: paletas, tokens (espaciado/radios/tipografía), stylesheet
    ├── iconos.py            # Catálogo de iconos SVG dibujados en código, coloreados por el tema
    ├── ui.py                # Kit de componentes (botones con icono, chips, avisos, tarjetas, contenedores responsive)
    ├── navegacion.py        # Catálogo de herramientas + barra lateral + pantalla de inicio
    │
    │   # ── Infraestructura ───────────────────────────────────────────
    ├── setup.py             # Rutas compatibles con PyInstaller + carga/guardado de config
    ├── dispositivos.py      # Capa única de impresoras y escáneres: validación, COM y errores traducidos
    ├── escaner_qt.py        # El hilo que abre el diálogo WIA sin congelar la ventana (lo comparten las dos herramientas)
    ├── imagen_pdf.py        # Imagen → PDF de una página (reportlab / img2pdf / Pillow), sin Qt
    ├── errores.py           # Manejador global de excepciones: log + aviso al usuario
    ├── version.py           # Única fuente de verdad de la versión (app, instalador y CI la leen de acá)
    ├── actualizaciones.py   # Lógica del actualizador: versiones, descarga y verificación SHA-256 (sin Qt)
    ├── actualizador.py      # Capa Qt del actualizador: workers y diálogo
    ├── settings.py          # Diálogo de ajustes de correo emisor (SMTP, credenciales)
    │
    │   # ── Herramienta: firmar un PDF ────────────────────────────────
    ├── trabajo.py           # Modelo del trabajo en curso: páginas, imágenes y rotaciones (lógica pura, sin Qt)
    ├── fase1_preview.py     # Cuadrícula de miniaturas y selección de página
    ├── fase2_print.py       # Integración con la impresora del sistema
    ├── fase3_scan.py        # Cola de escaneo: una imagen por página, con rotación
    ├── fase_guardar.py      # Lógica de reemplazo de página y guardado del PDF
    ├── fase4_email.py       # Flujo de envío: carpeta temporal + cliente de correo
    │
    │   # ── Herramienta: escanear a PDF ───────────────────────────────
    ├── documento_escaneado.py  # Modelo del documento que se arma: orden y rotación de páginas (sin Qt)
    └── herramienta_escaneo.py  # La pantalla: miniaturas, vista previa, reordenar y guardar
```

La separación **modelo sin Qt / pantalla** no es adorno: es lo que permite
que los tests cubran el reordenamiento de páginas, el parseo de rangos y el
saneamiento de nombres de archivo sin abrir una ventana ni tener un escáner
conectado.

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
| `Ctrl+0` | Ir al menú de herramientas |
| `Ctrl+1` | Abrir *Firmar un PDF* |
| `Ctrl+2` | Abrir *Escanear a PDF* |
| `Ctrl+O` | Abrir un PDF |
| `Ctrl+E` | Enviar por correo el documento seleccionado |
| `Ctrl+F` | Buscar en la lista de guardados |
| `Ctrl+D` | Alternar tema claro / oscuro |
| `F5` | Recargar la lista de documentos |
| `Enter` | Editar el documento seleccionado |

**En *Escanear a PDF*:** `Ctrl+N` escanea la hoja siguiente, `Ctrl+↑` / `Ctrl+↓`
mueven la página seleccionada, `Ctrl+S` guarda el documento y `Esc` vuelve al menú.

**Al elegir páginas:** `←` `→` `↑` `↓` recorren la cuadrícula, `Inicio`/`Fin`
saltan a la primera o última página, `Espacio` (o doble clic) abre la vista
previa grande, `Ctrl+A` selecciona todas, `Ctrl+F` va al campo de rangos,
`Enter` confirma y `Esc` sale.

**Selección múltiple:** clic alterna una página, `Shift+clic` marca un rango
desde la última tocada, y el campo *Páginas* acepta expresiones como
`1, 3, 5-8`.

**En la vista previa grande:** `←` `→` cambian de página, `Espacio` marca o
desmarca, `Esc` cierra.

**En escaneo y guardado:** `Esc` vuelve atrás y `Enter` confirma.

---

## Requisitos previos

- **Python** 3.10 o superior
- **Windows** para imprimir y escanear: la impresión usa GDI (`StretchDIBits`) y el escaneo usa WIA, ambos vía `pywin32`.
  El resto de la app (abrir, previsualizar, reemplazar página, guardar, enviar) funciona en cualquier sistema.
- **Escáner compatible** *(opcional — también se pueden cargar imágenes desde disco o arrastrarlas a la ventana)*:
  - Windows: WIA (integrado, compatible con HP LaserJet MFP)

> No hace falta Poppler ni `pdf2image`: el render lo hace **PyMuPDF** directamente.

---

## Instalación desde el código (desarrollo)

> Si sólo querés **usar** la app, no necesitás nada de esto: bajá el instalador
> desde [Releases](https://github.com/CrazyK-oss/pdf-sign-assistant/releases/latest).

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

El ejecutable se genera en `dist/PDF Sign Assistant/`. Distribuí **siempre la carpeta completa**, nunca solo el `.exe`.

> **Nota:** Si PyInstaller no encuentra `python3XX.dll`, el `.spec` incluye lógica para localizarla automáticamente usando `sys.base_exec_prefix` (funciona correctamente dentro de entornos virtuales).

---

## Publicar una versión

El build no se hace a mano: lo hace GitHub Actions en un Windows limpio, así no
hay "en mi máquina andaba".

```bash
# 1. Subir el número de versión (única fuente de verdad)
#    modules/version.py  →  __version__ = "0.8.0"

# 2. Commitear y etiquetar
git commit -am "release: v0.8.0"
git tag v0.8.0
git push origin main --tags
```

El workflow `.github/workflows/release.yml` corre los tests, compila con
PyInstaller, arma el instalador con Inno Setup, genera el ZIP portable y los
checksums, y publica todo en un Release nuevo. Si el tag no coincide con
`modules/version.py`, **falla a propósito** antes de publicar nada.

Para probar el build sin publicar: pestaña **Actions → Release → Run workflow**.
Los artefactos quedan disponibles 14 días.

### Sobre la firma de código

Los binarios van **sin firmar**, así que Windows SmartScreen muestra una
advertencia la primera vez. Es la principal fricción para un usuario no
técnico. Para eliminarla hace falta un certificado de firma de código:

| Tipo | Costo aprox. | Efecto |
|------|-------------|--------|
| Sin firma | — | SmartScreen advierte siempre |
| OV | ~150-400 USD/año | Advierte hasta acumular reputación (semanas) |
| EV | ~300-600 USD/año | Sin advertencia desde el día uno |

Cuando haya certificado, se agrega un paso de `signtool` en el workflow entre
el build y el instalador, con el `.pfx` y su contraseña en GitHub Secrets.

> **Detalle relevante:** el `.spec` usa `upx=False` a propósito. UPX achica el
> binario pero dispara falsos positivos de antivirus en ejecutables de
> PyInstaller, que es exactamente lo que no querés al distribuir.

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

### v0.11 — Caja de herramientas y UI nueva *(actual)*

**Iconos que se ven en todas las máquinas**
- Nuevo `modules/iconos.py`: **49 iconos dibujados en SVG dentro del código**, renderizados con `QSvgRenderer` y coloreados con el token del tema. Se rasterizan al DPI real de la pantalla y se cachean
- Se eliminó **hasta el último emoji de la interfaz**. El problema no era estético: un emoji se dibuja con la fuente del sistema, y si Windows no tiene el glifo lo degrada sin avisar. En la misma app, `⚙` se veía bien, `👁` salía como una raya y `🌙` como un punto — distinto en cada equipo
- Un test recorre el código fuente buscando cada `icono="…"` y falla si el nombre no está en el catálogo: un icono mal escrito ya no espera a que alguien abra esa pantalla
- Otro test dibuja los 49 y falla si Qt se queja de un trazo. `QSvgRenderer` **no lanza excepción** con un path roto: lo dibuja a medias y avisa por stderr, donde nadie mira (así se había colado la bombilla incompleta)

**Menú de herramientas**
- La ventana pasó de ser una pantalla a ser un contenedor: **barra lateral permanente** + pantalla de inicio con una tarjeta por herramienta
- La barra lateral se **colapsa a una tira de iconos** por debajo de 820 px, en vez de comerse un tercio del ancho útil
- El inicio muestra los documentos recientes y cuántos hay en total
- Agregar una herramienta nueva es sumar una entrada a `CATALOGO` en `modules/navegacion.py`: la barra lateral, el inicio y los atajos `Ctrl+N` salen de ahí

**Herramienta nueva: Escanear a PDF**
- Armá un documento nuevo hoja por hoja desde el escáner, con miniatura de cada página y vista previa grande de la seleccionada
- Reordenar (botones o `Ctrl+↑`/`Ctrl+↓`), girar de a 90°, invertir el taco entero y descartar páginas antes de guardar
- También acepta imágenes **arrastradas a la ventana** o importadas del disco
- Escanea a **300 DPI**, no a 600 como al firmar: es calidad de documento y pesa la cuarta parte — con 20 páginas la diferencia son cientos de megas
- Las miniaturas se leen **ya reducidas** con `QImageReader.setScaledSize()`. Cargar un escaneo A4 de 300 DPI con `QPixmap` para mostrarlo de 92 px son ~35 MB de RAM por página
- El PDF se escribe a un archivo temporal y **recién después se renombra**: si el proceso muere a mitad de la escritura, el archivo que ya tenías no queda truncado
- 8 tests de integración abren el PDF resultante y verifican los píxeles: que el orden de la pantalla sea el del documento, que la rotación se aplique a la página correcta, y que un fallo no deje basura a medio escribir

**Rediseño visual**
- Paleta nueva (neutros fríos + teal), tipografía y espaciado revisados
- Componentes nuevos en el kit: `Chip`, `Aviso`, `TarjetaHerramienta`, `Buscador`, `BotonIcono`
- **`BotonIcono` recolorea su icono solo**: el color va quemado en el pixmap, así que se regenera al pasar el mouse, al marcarse, al deshabilitarse y al cambiar el tema. Sin eso, un botón *secondary* en hover quedaba con el icono teal sobre fondo teal
- En modo oscuro, los botones de peligro y de éxito pasaron a **texto oscuro sobre el relleno claro**: blanco sobre rosa pastel no llegaba al contraste mínimo legible

**Reorganización**
- `modules/imagen_pdf.py` y `modules/escaner_qt.py` salieron de las fases: los usan las dos herramientas, y no correspondía que la nueva importara código de una fase de la vieja

### v0.10.1 — Red de seguridad

- **Manejador global de excepciones.** El `.exe` se compila con `console=False`: hasta ahora, una excepción que escapara mataba la aplicación **en silencio**, sin dejar rastro. Ahora queda en el log con traceback completo y el usuario ve un aviso que le dice qué pasó y dónde está el archivo para reportarlo. Cubre también los hilos, que tienen su propio hook desde Python 3.8
- **Tests de integración del guardado.** El pipeline central —imagen escaneada → PDF → reemplazo dentro del documento— no tenía **ni un test** en el repo. Ahora hay 7 que abren el PDF resultante y verifican los píxeles: que cada imagen aterrice en su página, que las no elegidas queden intactas, que la rotación no deforme, y que los metadatos registren las páginas firmadas. Se saltean solos en el CI liviano y corren en el job de Release, que instala las dependencias completas
- **El actualizador limpia lo que descarga.** Cada actualización dejaba un instalador de ~50 MB en el temporal del usuario, para siempre
- Acciones de GitHub actualizadas a las versiones que corren sobre **Node 24** (el runtime Node 20 quedó deprecado)

> Se revisó también el reemplazo de páginas con `/Rotate` (documentos escaneados con páginas giradas): el resultado es correcto —la firma queda vertical, como se escaneó— así que no hizo falta cambiar nada.

### v0.10 — Blindaje frente a drivers

**Capa única de dispositivos**
- Nuevo `modules/dispositivos.py`: **ningún otro módulo importa `win32*`**. Impresión, escaneo, enumeración y traducción de errores pasan todos por ahí
- Eso hace testeable lo que antes no lo era: el hardware no existe en CI, pero ahora se puede simular. **39 tests** nuevos, incluido un escáner falso que ejercita el flujo de adquisición completo

**Dos bugs reales corregidos**
- **COM nunca se inicializaba en el hilo del escáner.** `win32com.Dispatch` corría dentro de un `QThread` sin `CoInitialize()`: en Windows eso falla con *"CoInitialize has not been called"*, y el usuario recibía un "el escáner reportó un error" que lo mandaba a revisar cables cuando el problema era del código
- **Un driver que informa `0` reventaba la impresión.** DPI en 0 → `ZeroDivisionError`; área imprimible en 0 → escala 0 → **hoja impresa en blanco sin ningún aviso**. Pasa con impresoras virtuales y drivers genéricos. Ahora todo lo que informa el driver pasa por un saneador con valores de respaldo, y las correcciones quedan en el log

**Tolerancia a fallos**
- **Reintento a menor DPI**: si la impresora rechaza un bitmap grande (típico en impresoras de red y económicas), se reintenta a 200 y 150 DPI en vez de abortar el trabajo entero. Una hoja a 150 DPI es mejor que ninguna hoja
- El trabajo de impresión se **aborta correctamente** si algo falla a mitad de camino: uno abierto a medias traba la cola
- Mensajes distintos para "no es Windows", "falta pywin32" y **"no hay ninguna impresora/escáner instalado"**, cada uno con su sugerencia concreta
- Los errores de WIA se traducen: ocupado, sin papel, sin permisos, no está listo…
- Si hay **más de un escáner**, se deja elegir cuál usar
- Se verifica que el escáner haya devuelto un archivo real: antes, un escaneo vacío pasaba como éxito

### v0.9 — Actualizador interno

- **La app se actualiza sola.** Consulta una vez por día si hay versión nueva, avisa con las notas del Release renderizadas, y si el usuario acepta: descarga el instalador, **verifica su SHA-256** contra el `SHA256SUMS.txt` publicado, y lo ejecuta en silencio. Inno Setup cierra la app, actualiza y la vuelve a abrir
- Esto es posible **porque el instalador no pide permisos de administrador**: instalando en `Program Files` cada actualización mostraría un cartel de UAC y la actualización silenciosa sería inviable
- **Nunca instala nada sin confirmación**: automática es la comprobación, no la instalación
- **Falla en silencio**: una PC sin internet, detrás de un proxy o con el firewall cerrado no ve un error cada vez que abre la aplicación
- Opciones por versión: **"Ahora no"** y **"Omitir esta versión"** (que igual vuelve a avisar en la siguiente)
- En **modo portable** no se ofrece instalar —no hay instalador que correr—, sólo se enlaza la descarga
- Nuevo interruptor en **Ajustes → Actualizaciones**, con botón *Buscar ahora* y la versión instalada a la vista
- El repositorio es configurable, por si conviene apuntar a un servidor interno
- **38 tests nuevos** sobre comparación de versiones, política de comprobación y lectura de la respuesta del servidor (con datos falsos, sin salir a internet). Cubren el caso que rompe callado: que `1.9.0` no se considere posterior a `1.10.0` por comparar como texto

### v0.8 — Distribución: instalador, CI y rutas de usuario

**La app ya se puede instalar de verdad**
- **Instalador Inno Setup** (`installer/`): un `Setup.exe` con acceso directo y desinstalador. Instala en la carpeta del usuario con `PrivilegesRequired=lowest`, así **no aparece el cartel de UAC** — pedir permisos de administrador para una app que no toca el sistema es fricción que hace abandonar
- **ZIP portable** para usar desde un pendrive, sin instalar nada
- **GitHub Actions**: `ci.yml` corre lint y tests en cada push; `release.yml` compila en un Windows limpio al crear un tag `vX.Y.Z`, arma instalador + ZIP + checksums SHA256 y publica el Release. Si el tag no coincide con `modules/version.py`, falla antes de publicar
- **LICENSE MIT**: sin licencia, legalmente nadie podía usar ni redistribuir la app
- **Icono propio** en el ejecutable, la ventana y el instalador, y **propiedades de versión** en el `.exe` (antes aparecía sin nombre ni versión, lo que además alimenta las alertas de SmartScreen)

**Fix bloqueante para instalar en Program Files**
- La app escribía config, logs y PDFs **junto al ejecutable**. Instalada en `C:\Program Files` —que es de sólo lectura sin admin— habría fallado al guardar ajustes, escribir el log y guardar el documento firmado. Ahora:
  - Config y logs → `%LOCALAPPDATA%\PDF Sign Assistant`
  - Documentos firmados → `Documentos\PDF Sign Assistant`
  - La carpeta Documentos se resuelve con la API de Windows (`SHGetKnownFolderPath`), no asumiendo `~/Documents`: puede estar redirigida a OneDrive o a una unidad de red
- **Migración automática**: quien venía de una versión anterior no pierde nada — sus documentos y su configuración se mueven solos la primera vez. Nunca pisa datos nuevos con viejos
- **Modo portable** con un `portable.txt` junto al ejecutable, que vuelve al comportamiento anterior

**Calidad**
- **49 tests** en `tests/`, de lógica pura (sin Qt ni pantalla), corriendo en CI: modelo de dominio, configuración, rutas y migración
- `upx=False` en el `.spec`: UPX achica el binario pero **dispara falsos positivos de antivirus** en ejecutables de PyInstaller
- README reescrito de cara al usuario: sección de descarga arriba de todo, qué hacer con la advertencia de SmartScreen y dónde quedan sus archivos

### v0.7 — Firma de varias páginas por sesión

**Multipágina de punta a punta**
- **Selección múltiple** en la cuadrícula: clic alterna, `Shift+clic` marca un rango, `Ctrl+A` selecciona todas y un campo de texto acepta expresiones tipo `1, 3, 5-8`
- **Vista previa grande** (doble clic o `Espacio`): la página completa, con navegación por flechas y selección desde ahí. Los thumbnails no alcanzan cuando el documento tiene hojas parecidas entre sí
- **Un solo trabajo de impresión** para todas las páginas elegidas: la cola de la impresora muestra un único ítem y ningún otro trabajo se intercala en el medio. Se renderiza de a una página por vez, así 20 hojas no levantan cientos de MB
- **Cola de escaneo**: una fila por página, con su miniatura y su estado. "Digitalizar siguiente" salta sola a la próxima pendiente al terminar cada escaneo; "Cargar imágenes…" y el drag & drop aceptan varios archivos y los reparten en orden
- **Reemplazo múltiple** en una sola pasada de escritura, con progreso repartido entre las páginas

**Lógica reforzada**
- Nuevo `modules/trabajo.py`: el estado del trabajo (páginas, imágenes, rotaciones) deja de estar suelto en atributos de la ventana y pasa a un modelo con invariantes garantizadas — selección siempre ordenada y dentro de rango, sin imágenes huérfanas de páginas que se quitaron. Es lógica pura, sin Qt, y está cubierta por tests
- Volver atrás en cualquier fase **conserva lo ya hecho**: la selección de páginas y las imágenes asignadas sobreviven al ir y venir entre pantallas
- Se corrigió el resumen del correo, que decía **"página 1" fijo** sin importar qué se hubiera firmado: ahora las páginas quedan registradas en los metadatos del PDF (`/PSAPaginas`) y se leen al enviarlo o al re-editarlo
- Al re-editar un documento ya firmado, la app **propone de entrada las mismas páginas**
- Validaciones nuevas: páginas fuera del rango del documento, imágenes que desaparecieron entre el escaneo y el guardado, y páginas pendientes al intentar guardar

**Funciones nuevas**
- **Rotación por página** (`-90°` / `+90°`): el escáner devuelve la hoja al revés muy seguido. La rotación se aplica al generar el PDF y **nunca toca el archivo original**. Verificado que coincide exactamente con lo que muestra la vista previa
- **Aviso de orientación cruzada**: si la imagen es apaisada y la página es vertical (o viceversa), la fila lo señala — casi siempre es un escaneo mal orientado
- **Log a archivo** en `logs/pdf_sign_assistant.log`, con rotación a 512 KB y 3 archivos de historial. El `.exe` se compila con `console=False`, así que hasta ahora **cualquier error en la máquina del usuario se perdía sin dejar rastro**
- **Limpieza de copias huérfanas**: `pdfs_trabajo/` acumulaba archivos para siempre si la app se cerraba de golpe; ahora se borran las de más de 7 días al arrancar
- **Variante compacta de botón** en el sistema de diseño, para acciones angostas cuyo texto no entraba con el padding normal

### v0.6 — Rendimiento, estandarización visual y responsive

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

### v0.5 — Flujo de envío con carpeta temporal
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

- [x] ~~**Firma de múltiples páginas** — seleccionar y procesar varias páginas en una sola sesión~~ *(v0.7)*
- [x] ~~**Menú de herramientas** — una ventana que aloje varias herramientas de PDF~~ *(v0.11)*
- [x] ~~**Escanear a PDF** — armar un documento nuevo desde el escáner~~ *(v0.11)*
- [ ] **Unir y dividir PDFs** — combinar documentos o extraer un rango de páginas
- [ ] **Procesamiento por lotes** — poner en cola varios PDFs y firmarlos secuencialmente
- [ ] **Firma digital criptográfica** — incrustar firmas digitales sin necesidad de imprimir
- [ ] **Exportar como ZIP** — empaquetar el PDF firmado junto con sus imágenes escaneadas
- [ ] **Soporte macOS** — integración nativa con impresoras y escáneres vía CUPS / ImageCapture
- [x] ~~**Persistencia del tema** — recordar la preferencia de tema claro/oscuro entre sesiones~~ *(v0.6)*

---

## Sobre los drivers

**No se unifican drivers, y no se puede.** Los distribuye el fabricante y los
instala Windows: una aplicación no puede empaquetarlos ni reemplazarlos. Lo que
sí existe es la capa de unificación del propio sistema, y es la que usa esta
app:

| Dispositivo | API | Por qué |
|-------------|-----|---------|
| Impresora | **GDI** (`StretchDIBits` sobre el printer DC) | Escribe los píxeles directo, sin que ICM ni GDI+ toquen el color |
| Escáner | **WIA** | Estándar de Windows; el fabricante provee el driver |

Lo que sí se unifica es **nuestro lado**: todo el acceso a dispositivos pasa por
`modules/dispositivos.py`. Ningún otro módulo importa `win32*`. Eso da un único
lugar donde validar, traducir errores y, sobre todo, **testear** — el hardware no
existe en CI, así que la lógica tiene que ser aislable.

### Los drivers mienten

La capa asume que un driver puede devolver cualquier cosa, y lo corrige:

| Lo que informa el driver | Qué pasaba antes | Qué hace ahora |
|--------------------------|------------------|----------------|
| `0` DPI | `ZeroDivisionError` — la impresión reventaba | Usa 300 DPI y lo anota en el log |
| `0` de área imprimible | Escala 0 → **hoja impresa en blanco, sin aviso** | Asume A4 y lo anota |
| Valores absurdos (10⁶ DPI) | Bitmap gigante → sin memoria | Se acota a un rango razonable |
| Rechaza un bitmap grande | Se abortaba todo el trabajo | Reintenta a 200 y 150 DPI |

### ¿Y TWAIN?

Sería el respaldo para escáneres viejos que no exponen WIA. **No está implementado
a propósito:** el DSM de TWAIN arrastra un problema de 32 vs 64 bits que cuesta más
de lo que resuelve. La puerta queda abierta —`dispositivos.py` es el único lugar a
tocar— para cuando aparezca un escáner concreto que lo necesite.

---

## Notas técnicas

- Solo puede haber **un PDF en proceso** a la vez; el botón "Abrir PDF" se deshabilita hasta que la sesión actual se cierre o complete.
- Las copias de trabajo se guardan en `pdfs_trabajo/` y se limpian automáticamente al guardar o cancelar.
- Los documentos firmados se persisten en `pdfs_firmados/` y aparecen en la ventana principal con su fecha de modificación.
- La carpeta `pdfs_firmados/_envio_temp/` es estrictamente temporal — no guardes archivos importantes ahí.
- Hacer doble clic en un documento guardado lo reabre para re-editar sin modificar el original.
- Todos los errores se muestran como diálogos amigables; los tracebacks detallados se imprimen en consola para depuración.
- La conversión imagen → PDF intenta tres motores en orden: **reportlab** → **img2pdf** (en subproceso aislado, porque puede crashear a nivel de extensión C) → **Pillow**.
- **COM se inicializa en el hilo del escáner** (`CoInitialize`/`CoUninitialize` en STA). pywin32 no lo hace solo en hilos nuevos: sin eso, toda llamada a WIA falla con *"CoInitialize has not been called"*, y el usuario veía un error genérico que lo mandaba a revisar cables.
- Los `com_error` de WIA se traducen a mensajes con causa y sugerencia. Un `0x80210006` crudo no le dice nada a nadie; "El escáner está ocupado" sí.
- Si hay **más de un escáner** instalado, se muestra el selector de WIA. Antes se usaba siempre el predeterminado, sin decir cuál era.
- El actualizador **verifica el SHA-256** del instalador descargado contra el `SHA256SUMS.txt` del Release antes de ejecutarlo. Eso protege la integridad de la descarga (corrupción, intercepción), pero no cubre un repositorio comprometido: para eso hace falta firma de código.
- La actualización silenciosa es posible **porque el instalador no pide permisos de administrador**. Si instalara en `Program Files`, cada actualización dispararía un cartel de UAC.
- La comprobación de actualizaciones se espacia 24 h y se hace 3 segundos después de abrir la app, para no retrasar el arranque. Falla en silencio si no hay internet o hay un proxy de por medio.
- El repositorio de actualizaciones es configurable (`repo_actualizaciones` en `config.json`), por si algún día conviene apuntar a un servidor interno.
- La app **no escribe junto al ejecutable**: config y logs van a `%LOCALAPPDATA%\PDF Sign Assistant` y los documentos a `Documentos\PDF Sign Assistant`. Eso es lo que permite instalarla en `Program Files`, que es de sólo lectura sin permisos de administrador. Un `portable.txt` junto al ejecutable vuelve al comportamiento anterior (todo al lado de la app).
- La ventana principal vigila la carpeta de documentos firmados con `QFileSystemWatcher`: si agregás o borrás archivos desde el Explorador, la lista se actualiza sola.
- Las páginas firmadas quedan registradas en los metadatos del PDF, bajo la clave `/PSAPaginas` (índices 0-based separados por coma). Los documentos firmados con versiones anteriores no la tienen: en ese caso el resumen del correo indica "no registradas".
- La rotación de una hoja escaneada **no modifica la imagen original**: se aplica sobre una copia temporal al momento de generar el PDF.
- Si la app se cierra de golpe, las copias de trabajo quedan en `pdfs_trabajo/`; las de más de 7 días se borran solas en el siguiente arranque.
