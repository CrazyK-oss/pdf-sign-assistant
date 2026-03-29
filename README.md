# PDF Sign Assistant

App de escritorio en Python para automatizar el flujo de trabajo de firma de documentos legales.
Diseñada para usuarios no técnicos con interfaz simple, botones grandes y retroalimentación clara.

## Flujo de uso

1. **Seleccionar documento**: Elige el PDF que necesita firmar desde la carpeta `documents/`
2. **Seleccionar páginas**: Vista previa visual; toca las páginas que necesitas imprimir y firmar
3. **Imprimir**: La app imprime solo las páginas seleccionadas y espera que las firmes físicamente
4. **Escanear**: Escanea cada página firmada; la app las reemplaza automáticamente en el PDF
5. **Enviar**: Ingresa el correo del destinatario, revisa el resumen y envía

## Estructura del proyecto

```
pdf-sign-assistant/
├── main.py                  # Punto de entrada y flujo principal
├── config.json              # Configuración (credenciales SMTP, rutas)
├── requirements.txt         # Dependencias Python
├── README.md
├── documents/               # PDFs originales (NO se suben al repo)
├── scans/                   # Escaneos temporales (NO se suben al repo)
├── temp/                    # Archivos temporales (NO se suben al repo)
└── modules/
    ├── __init__.py
    ├── setup.py             # Configuración y creación de carpetas
    ├── fase1_preview.py     # Vista previa y selección de páginas
    ├── fase2_print.py       # Impresión de páginas seleccionadas
    ├── fase3_scan.py        # Escaneo y reemplazo de páginas
    └── fase4_email.py       # Envío por correo con resumen
```

## Setup

### 1. Requisitos previos

- Python 3.10+
- **Poppler** (requerido por `pdf2image`):
  - **Windows**: Descargar de https://github.com/oschwartz10612/poppler-windows/releases/ y agregar la carpeta `bin` al PATH
  - **Linux**: `sudo apt-get install poppler-utils`
  - **macOS**: `brew install poppler`
- **Escáner compatible**:
  - Linux: `scanimage` (paquete `sane-utils`)
  - Windows: WIA (incluido en Windows, compatible con HP Laser MFP 135w)

### 2. Instalación

```bash
# Clonar repositorio
git clone https://github.com/CrazyK-oss/pdf-sign-assistant.git
cd pdf-sign-assistant

# Crear entorno virtual
python -m venv venv

# Activar entorno
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux/macOS

# Instalar dependencias
pip install -r requirements.txt
```

### 3. Configurar config.json

Edita `config.json` con tus credenciales reales:

```json
{
    "email_user": "tucorreo@gmail.com",
    "email_password": "tu_contraseña_de_aplicacion",
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "documents_folder": "documents",
    "scans_folder": "scans",
    "temp_folder": "temp"
}
```

> **Nota para Gmail**: Usa una *Contraseña de Aplicación* (no tu contraseña normal).  
> Actívala en: Google Account → Seguridad → Verificación en dos pasos → Contraseñas de aplicación

### 4. Colocar documentos

Copia los PDFs originales que necesitas firmar a la carpeta `documents/`.

### 5. Ejecutar

```bash
python main.py
```

## Notas técnicas

- Las carpetas `documents/`, `scans/` y `temp/` se crean automáticamente al iniciar la app
- Los archivos temporales de escaneo se guardan en `scans/` con nombres `scan_001.tiff`, `scan_002.tiff`, etc.
- El PDF firmado final se guarda en `temp/documento_firmado.pdf` antes de enviarse
- Todos los errores muestran mensajes amigables al usuario y se registran en la consola para depuración
