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
- ✉️ **Envío por correo SMTP** — enviá documentos firmados directamente desde la app
- ⚙️ **Panel de ajustes** — configurá el correo emisor (servidor, puerto, credenciales) desde la UI, sin tocar archivos de configuración
- 🌙 **Modo claro y oscuro** — alternás con un clic; el tema se aplica a toda la interfaz en tiempo real
- 🔒 **Cancelación segura** — cancelá en cualquier etapa sin corromper el archivo original

---

## Flujo de trabajo

```
Abrir PDF  →  Vista previa  →  Imprimir página  →  Escanear página firmada  →  Guardar PDF
```

| Paso | Módulo | Descripción |
|------|--------|-------------|
| 1 | `main.py` | Abrir un PDF y cargarlo en la sesión de trabajo |
| 2 | `fase1_preview.py` | Cuadrícula desplazable de miniaturas; selección de la página objetivo |
| 3 | `fase2_print.py` | Envío de la página seleccionada a la impresora del sistema |
| 4 | `fase3_scan.py` | Carga de la imagen escaneada/fotografiada de la página firmada |
| 5 | `fase_guardar.py` | Vista previa del resultado, confirmación y guardado del PDF firmado |
| 6 | `fase4_email.py` | Envío del PDF firmado por correo SMTP con adjunto |

---

## Estructura del proyecto

```
pdf-sign-assistant/
├── main.py                  # Punto de entrada · ventana principal · orquestación del flujo
├── config.json              # Credenciales SMTP y rutas de carpetas
├── config.example.env       # Plantilla de variables de entorno
├── requirements.txt         # Dependencias de Python
├── pdf_sign_assistant.spec  # Configuración de PyInstaller para generar el .exe
├── pdfs_trabajo/            # Copias de trabajo temporales (auto-creado, gitignored)
├── pdfs_firmados/           # Documentos firmados finales (auto-creado, gitignored)
└── modules/
    ├── __init__.py
    ├── setup.py             # Inicialización y rutas compatibles con PyInstaller
    ├── theme.py             # Sistema de diseño: paletas light/dark, stylesheet, helpers de fuente
    ├── settings.py          # Diálogo de ajustes de correo emisor (SMTP, credenciales)
    ├── fase1_preview.py     # Cuadrícula de miniaturas y selección de página
    ├── fase2_print.py       # Integración con la impresora del sistema
    ├── fase3_scan.py        # Carga de imagen y vista previa del escaneo
    ├── fase_guardar.py      # Lógica de reemplazo de página y guardado del PDF
    └── fase4_email.py       # Envío por correo SMTP con adjunto PDF
```

---

## Requisitos previos

- **Python** 3.10 o superior
- **Poppler** — requerido por `pdf2image` para renderizar PDFs:
  - **Windows**: Descargar desde [oschwartz10612/poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases/) y agregar la carpeta `bin/` al `PATH` del sistema
  - **Linux**: `sudo apt-get install poppler-utils`
  - **macOS**: `brew install poppler`
- **Escáner compatible** *(opcional — también se pueden cargar imágenes desde disco)*:
  - Windows: WIA (integrado, compatible con HP LaserJet MFP)
  - Linux: `scanimage` vía `sane-utils`

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

Los cambios se guardan automáticamente en `config.json`.

### Opción B — Editar `config.json` directamente

```json
{
    "email_user": "tucorreo@dominio.com",
    "email_password": "tu_contraseña_de_aplicacion",
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587
}
```

> **Usuarios de Gmail:** Usá una *Contraseña de Aplicación*, no tu contraseña normal.  
> Activála en: **Cuenta de Google → Seguridad → Verificación en dos pasos → Contraseñas de aplicación**

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
| `reportlab` | Utilidades de generación de PDFs |
| `watchdog` | Monitoreo de eventos del sistema de archivos |
| `pywin32` | Integración con impresora y escáner WIA en Windows |
| `python-dotenv` | Carga de archivos `.env` |

---

## Changelog

### v0.4 — Rediseño UI/UX + Modo Oscuro *(actual)*
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
- [ ] **Persistencia del tema** — recordar la preferencia de tema claro/oscuro entre sesiones

---

## Notas técnicas

- Solo puede haber **un PDF en proceso** a la vez; el botón "Abrir PDF" se deshabilita hasta que la sesión actual se cierre o complete.
- Las copias de trabajo se guardan en `pdfs_trabajo/` y se limpian automáticamente al guardar o cancelar.
- Los documentos firmados se persisten en `pdfs_firmados/` y aparecen en la ventana principal con su fecha de modificación.
- Hacer doble clic en un documento guardado lo reabre para re-editar sin modificar el original.
- Todos los errores se muestran como diálogos amigables; los tracebacks detallados se imprimen en consola para depuración.
