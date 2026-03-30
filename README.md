# PDF Sign Assistant

> Aplicación de escritorio en Python + PyQt6 para automatizar el flujo completo de firma de documentos legales — diseñada para usuarios no técnicos con una interfaz clara y guiada.

---

## Descripción

**PDF Sign Assistant** simplifica el proceso de firmar documentos PDF físicamente y producir una copia digital actualizada. En lugar de editar PDFs manualmente o gestionar imágenes escaneadas sueltas, la app guía al usuario paso a paso: previsualizar páginas → imprimir → escanear → incrustar → guardar → enviar.

Toda la interacción ocurre desde una sola ventana con controles grandes, bien etiquetados y retroalimentación de estado en tiempo real.

---

## Funcionalidades

- 📄 **Vista previa en cuadrícula** — visualizá todas las páginas del PDF antes de elegir cuál firmar
- 🖨️ **Impresión directa** — envía la página seleccionada a la impresora automáticamente
- 🖼️ **Integración con escáner** — cargá o capturá la imagen escaneada de la página firmada
- 🔄 **Reemplazo de página** — incrusta la firma escaneada de vuelta en el PDF original en la posición correcta
- 💾 **Lista de trabajos guardados** — historial de documentos procesados con fecha y hora; permite re-editar
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

---

## Estructura del proyecto

```
pdf-sign-assistant/
├── main.py                  # Punto de entrada · ventana principal · orquestación del flujo
├── config.json              # Credenciales SMTP y rutas de carpetas
├── config.example.env       # Plantilla de variables de entorno
├── requirements.txt         # Dependencias de Python
├── pdfs_trabajo/            # Copias de trabajo temporales (auto-creado, gitignored)
├── pdfs_firmados/           # Documentos firmados finales (auto-creado, gitignored)
└── modules/
    ├── __init__.py
    ├── setup.py             # Inicialización y creación de carpetas
    ├── fase1_preview.py     # Cuadrícula de miniaturas y selección de página
    ├── fase2_print.py       # Integración con la impresora del sistema
    ├── fase3_scan.py        # Carga de imagen y vista previa del escaneo
    ├── fase_guardar.py      # Lógica de reemplazo de página y guardado del PDF
    └── fase4_email.py       # Envío por correo SMTP con adjunto PDF *(en desarrollo)*
```

---

## Requisitos previos

- **Python** 3.10 o superior
- **Poppler** — requerido por `pdf2image` para renderizar PDFs:
  - **Windows**: Descargar desde [oschwartz10612/poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases/) y agregar la carpeta `bin/` al `PATH` del sistema
  - **Linux**: `sudo apt-get install poppler-utils`
  - **macOS**: `brew install poppler`
- **Escáner compatible** *(opcional — también se pueden cargar imágenes desde disco)*:
  - Linux: `scanimage` vía `sane-utils`
  - Windows: WIA (integrado, compatible con HP LaserJet MFP)

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

### `config.json` — SMTP y rutas de carpetas

Editá este archivo con tus credenciales antes de ejecutar la app:

```json
{
    "email_user": "tucorreo@dominio.com",
    "email_password": "tu_contraseña_de_aplicacion",
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "documents_folder": "./documents",
    "scans_folder": "./scans",
    "temp_folder": "./temp"
}
```

### `.env` — sobreescritura por variables de entorno *(opcional)*

Copiá `config.example.env` como `.env` y completá tus datos:

```env
EMAIL_REMITENTE=tucorreo@dominio.com
EMAIL_PASSWORD=tu_contraseña_de_aplicacion
```

> **Usuarios de Gmail:** Usá una *Contraseña de Aplicación*, no tu contraseña normal.  
> Activála en: **Cuenta de Google → Seguridad → Verificación en dos pasos → Contraseñas de aplicación**

---

## Ejecutar la app

```bash
python main.py
```

La app crea automáticamente las carpetas `pdfs_trabajo/` y `pdfs_firmados/` al iniciarse por primera vez. No se requiere configuración adicional.

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

## Roadmap

Mejoras planeadas para próximas versiones:

- [ ] **Soporte para macOS** — integración nativa con impresoras y escáneres vía CUPS / ImageCapture
- [ ] **Firma de múltiples páginas** — seleccionar y procesar varias páginas en una sola sesión
- [ ] **Envío automático por correo** — pulir y estabilizar el flujo SMTP integrado en la app
- [ ] **Procesamiento por lotes** — poner en cola varios PDFs y firmarlos secuencialmente
- [ ] **Firma digital criptográfica** — incrustar firmas digitales sin necesidad de imprimir físicamente
- [ ] **Panel de configuración en la UI** — gestionar SMTP, carpetas y escáner desde dentro de la app
- [ ] **Exportar como ZIP** — empaquetar el PDF firmado junto con sus imágenes escaneadas para archivo

---

## Notas técnicas

- Solo puede haber **un PDF en proceso** a la vez; el botón "Abrir PDF" se deshabilita hasta que la sesión actual se cierre o complete.
- Las copias de trabajo se guardan en `pdfs_trabajo/` y se limpian automáticamente al guardar o cancelar.
- Los documentos firmados se persisten en `pdfs_firmados/` y aparecen en la ventana principal con su fecha de modificación.
- Hacer doble clic en un documento guardado lo reabre para re-editar sin modificar el original.
- Todos los errores se muestran como diálogos amigables al usuario; los tracebacks detallados se imprimen en consola para depuración.
