# Changelog

Todos los cambios que se ven desde afuera, versión por versión.

Este archivo **no es documentación de cortesía**: el workflow de Release
extrae de acá la sección de la versión que se está publicando y la usa como
notas del Release, y el actualizador interno muestra exactamente ese texto
cuando avisa que hay algo nuevo. Si una versión no tiene su sección, el
build falla antes de publicar.

Los encabezados de versión son `## X.Y.Z`, con el mismo número que el tag
(`vX.Y.Z`) y que `modules/version.py`. Un test lo verifica.

## 0.12.0 — Documentos que entran en un correo

**El PDF pesaba demasiado para mandarlo**
- El documento firmado existe para enviarse por correo, y no entraba. La imagen se embebía **sin pérdida**, que para un escaneo —papel con ruido, tinta, sombras— es la peor opción posible. Medido sobre un A4 real: **3,4 MB por hoja** a 600 dpi. Seis hojas y Outlook ya rechazaba el adjunto, después de haber impreso, firmado y escaneado todo
- Ahora la página se remuestrea y se embebe como JPEG. reportlab lo copia **tal cual** al PDF (filtro DCTDecode), sin recodificar, así que la pérdida ocurre una sola vez
- Con la calidad por defecto, la misma hoja pasa de 3,4 MB a **0,26 MB**. Donde antes entraban 5 páginas firmadas en un correo, ahora entran **75**

**Elegís cuánto comprimir**
- Selector de calidad en las dos pantallas de guardado: **Alta** (300 dpi), **Equilibrada** (200 dpi, la de fábrica), **Mínima** (150 dpi) y **Sin comprimir**, que conserva el comportamiento anterior
- Los números salen de comparar los recortes a ojo: a 200 dpi el texto y el trazo de la firma son indistinguibles del original, y recién a 150 se empieza a notar el texto más lavado
- La calidad elegida se recuerda: quien la baja una vez suele necesitarla siempre, porque su correo tiene el mismo límite mañana

**Avisos antes de que sea tarde**
- Si el archivo guardado supera el límite, la pantalla lo dice y ofrece **volver a guardarlo con la calidad siguiente**, en vez de dejar que el usuario lo descubra al adjuntarlo
- La pantalla de envío muestra el peso del adjunto antes de abrir el cliente de correo, en rojo si no entra y en ámbar si está cerca del tope
- El límite (20 MB, el de Outlook y Exchange) es configurable: muchas organizaciones lo tienen más bajo

**Robustez**
- El remuestreo recalcula el DPI desde los píxeles que quedaron, para que el tamaño físico de la página no se mueva. No puede quedar exacto porque JFIF guarda la densidad como entero, pero el error queda por debajo de 1 punto (0,35 mm)
- Comprimir es una mejora, no un requisito: si Pillow falta o la imagen no se puede leer, se guarda el original en vez de fallar el guardado entero

## 0.11.1 — El actualizador dice qué cambió

- **El aviso de actualización ahora muestra el changelog.** Antes mostraba el cuerpo del Release, que era una plantilla fija con instrucciones de descarga: dónde bajar el `.exe`, la advertencia de SmartScreen, dónde quedan los archivos. Le explicaba al usuario cómo descargar algo que la app ya estaba por descargar sola, y no le decía **qué cambió**
- Nuevo `CHANGELOG.md` como única fuente de verdad. El workflow de Release extrae de ahí la sección de la versión que publica y la pone **antes** de las instrucciones, separada por un comentario HTML que GitHub no muestra; la app corta ahí y enseña sólo la primera mitad
- Si una versión no tiene su sección, el build **falla antes de publicar** en vez de sacar notas vacías. Y un test lo detecta antes todavía, al subir el número de versión, sin gastar un runner de Windows compilando el `.exe`
- El título del Release ahora lleva el nombre de la versión: *PDF Sign Assistant 0.11.1 — El actualizador dice qué cambió*
- Las notas se muestran en un `QTextBrowser` con enlaces clicables, y el diálogo abre con el foco en **Actualizar ahora** en vez de en el panel de texto
- El README ya no duplica el changelog: lo enlaza

**Vista previa nítida**
- **La vista previa se veía blanda porque se agrandaba.** Se leía con un tope fijo de 420 px y después se escalaba al panel, pero el panel crece con la ventana: medido, agrandaba 1,14× en una ventana de 1000 px y **2,63× en una de 2560**. Ahora se pide la imagen al tamaño que el panel ocupa de verdad, así que nunca se estira
- En pantallas con escalado (125 %, 150 %) tampoco se contemplaba el `devicePixelRatio`, que era la otra mitad del mismo problema. Ahora la previa y las miniaturas piden los píxeles reales del monitor
- El cache de imágenes pasó a acotarse **por bytes** (96 MB) en vez de por cantidad de entradas. El tope de 160 entradas estaba pensado para miniaturas de medio mega; con la previa pidiendo pixmaps de varios MB, esas mismas 160 entradas habrían permitido más de un gigabyte sin que nadie lo notara
- Al vaciar el documento o cerrar la herramienta, el cache se libera

## 0.11.0 — Caja de herramientas y UI nueva

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

## 0.10.1 — Red de seguridad

- **Manejador global de excepciones.** El `.exe` se compila con `console=False`: hasta ahora, una excepción que escapara mataba la aplicación **en silencio**, sin dejar rastro. Ahora queda en el log con traceback completo y el usuario ve un aviso que le dice qué pasó y dónde está el archivo para reportarlo. Cubre también los hilos, que tienen su propio hook desde Python 3.8
- **Tests de integración del guardado.** El pipeline central —imagen escaneada → PDF → reemplazo dentro del documento— no tenía **ni un test** en el repo. Ahora hay 7 que abren el PDF resultante y verifican los píxeles: que cada imagen aterrice en su página, que las no elegidas queden intactas, que la rotación no deforme, y que los metadatos registren las páginas firmadas. Se saltean solos en el CI liviano y corren en el job de Release, que instala las dependencias completas
- **El actualizador limpia lo que descarga.** Cada actualización dejaba un instalador de ~50 MB en el temporal del usuario, para siempre
- Acciones de GitHub actualizadas a las versiones que corren sobre **Node 24** (el runtime Node 20 quedó deprecado)

> Se revisó también el reemplazo de páginas con `/Rotate` (documentos escaneados con páginas giradas): el resultado es correcto —la firma queda vertical, como se escaneó— así que no hizo falta cambiar nada.

## 0.10.0 — Blindaje frente a drivers

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

## 0.9.0 — Actualizador interno

- **La app se actualiza sola.** Consulta una vez por día si hay versión nueva, avisa con las notas del Release renderizadas, y si el usuario acepta: descarga el instalador, **verifica su SHA-256** contra el `SHA256SUMS.txt` publicado, y lo ejecuta en silencio. Inno Setup cierra la app, actualiza y la vuelve a abrir
- Esto es posible **porque el instalador no pide permisos de administrador**: instalando en `Program Files` cada actualización mostraría un cartel de UAC y la actualización silenciosa sería inviable
- **Nunca instala nada sin confirmación**: automática es la comprobación, no la instalación
- **Falla en silencio**: una PC sin internet, detrás de un proxy o con el firewall cerrado no ve un error cada vez que abre la aplicación
- Opciones por versión: **"Ahora no"** y **"Omitir esta versión"** (que igual vuelve a avisar en la siguiente)
- En **modo portable** no se ofrece instalar —no hay instalador que correr—, sólo se enlaza la descarga
- Nuevo interruptor en **Ajustes → Actualizaciones**, con botón *Buscar ahora* y la versión instalada a la vista
- El repositorio es configurable, por si conviene apuntar a un servidor interno
- **38 tests nuevos** sobre comparación de versiones, política de comprobación y lectura de la respuesta del servidor (con datos falsos, sin salir a internet). Cubren el caso que rompe callado: que `1.9.0` no se considere posterior a `1.10.0` por comparar como texto

## 0.8.0 — Distribución: instalador, CI y rutas de usuario

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

## 0.7.0 — Firma de varias páginas por sesión

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

## 0.6.0 — Rendimiento, estandarización visual y responsive

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

## 0.5.0 — Flujo de envío con carpeta temporal
- **Nuevo flujo de envío** (`fase4_email.py`): copia el PDF a `pdfs_firmados/_envio_temp/` y abre el cliente de correo y el Explorador simultáneamente
- **Limpieza automática** de `_envio_temp/` a los 30 minutos vía hilo daemon
- **Limpieza al inicio** de la app: si quedó una carpeta temporal de una sesión anterior, se elimina antes de mostrar la ventana
- **Fix crítico impresión** (`fase2_print.py`): reemplazado el flujo `CreateBitmap/SelectObject` por `ImageWin.Dib.draw()` para eliminar el error `Select bitmap object failed`

## 0.4.0 — Rediseño UI/UX + Modo Oscuro
- **Sistema de diseño unificado** (`modules/theme.py`) con paletas `LIGHT` y `DARK` y stylesheet centralizado
- **Toggle claro/oscuro** en el header — se aplica a toda la interfaz en tiempo real
- **Fix crítico:** eliminado `QFormLayout.removeRow()` en `settings.py` que causaba crash al abrir el diálogo de ajustes
- **Fix:** fuentes definidas con `font_pt()` (siempre `>= 1`) para eliminar el warning `QFont::setPointSize: Point size <= 0`
- Rediseño visual completo: nuevos tokens de color, bordes, radios, scrollbars y estados hover/focus
- Botones con jerarquía clara: primario / secundario / ghost

## 0.3.0 — Panel de Ajustes de Correo
- Nuevo módulo `modules/settings.py` con `DialogoAjustes`
- Presets SMTP para Gmail, Outlook, Yahoo y Zoho
- Toggle mostrar/ocultar contraseña
- Validación de campos antes de guardar
- Persistencia directa en `config.json`

## 0.2.0 — Configuración PyInstaller
- `pdf_sign_assistant.spec` para generar ejecutables Windows
- Detección automática de `python3XX.dll` usando `sys.base_exec_prefix` (venv-safe)
- Bundle de DLLs de pywin32 y datos de PyQt6/fitz

## 0.1.0 — Flujo base
- Flujo completo: abrir → previsualizar → imprimir → escanear → guardar → enviar
- Lista de trabajos guardados con re-edición
- Cancelación segura en cualquier etapa

---
