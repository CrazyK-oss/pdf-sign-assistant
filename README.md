# PDF Sign Assistant
App para automatizar el flujo de trabajo de firma de documentos para usuarios no tecnológicos.

## Características
- Vista previa de PDF para seleccionar páginas a imprimir/firmar
- Gestión de impresión y escaneo
- Reemplazo automático de páginas firmadas
- Envío por email con resumen

## Setup
1. `python -m venv venv`
2. `venv\Scripts\activate` (cmd) o `.\venv\Scripts\Activate.ps1` (PowerShell)
3. `pip install -r requirements.txt` (crearemos este archivo pronto)
4. Configurar `config.json` con credenciales de email
5. Colocar PDFs originales en `./documents/`