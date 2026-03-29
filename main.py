import os
import json
import PySimpleGUI as sg
from pathlib import Path
from PyPDF2 import PdfReader, PdfWriter
import subprocess
import time
from pdf2image import convert_from_path
from io import BytesIO
import base64
# Importaremos otras librerías según las necesitemos (pdf2image, yagmail, etc.) en cada fase

# ======================
# CONFIGURACIÓN INICIAL
# ======================
def setup_directories():
    """Crea automáticamente las carpetas necesarias si no existen"""
    base_dir = Path(__file__).parent
    folders = ["documents", "scans", "temp"]
    
    for folder in folders:
        folder_path = base_dir / folder
        folder_path.mkdir(exist_ok=True)
        print(f"✅ Carpeta verificada/creada: {folder_path}")
    
    return base_dir

def load_config():
    """Carga configuración desde config.json"""
    config_path = Path(__file__).parent / "config.json"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        print("✅ Configuración cargada desde config.json")
        return config
    except FileNotFoundError:
        sg.popup_error("Error: No se encontró config.json. Por favor créelo siguiendo el README.md")
        exit(1)
    except json.JSONDecodeError:
        sg.popup_error("Error: config.json tiene formato JSON inválido")
        exit(1)

# ======================
# FASE 1: VISTA PREVIA Y SELECCIÓN DE PÁGINAS
# ======================
def seleccionar_paginas_pdf(ruta_pdf: str) -> list[int] | None:
    """
    Muestra una interfaz para seleccionar páginas de un PDF mediante miniaturas.
    
    Args:
        ruta_pdf: Ruta absoluta o relativa al archivo PDF
        
    Returns:
        Lista de índices de páginas seleccionadas (0-based) si el usuario confirma,
        None si cierra la ventana o cancela.
        
    Nota: Requiere que poppler esté instalado y accesible en PATH (para pdf2image).
          En Windows: descargar de https://github.com/oschwartz10612/poppler-windows/releases/
          En Linux: sudo apt-get install poppler-utils
    """
    # --- VALIDACIÓN INICIAL ---
    pdf_path = Path(ruta_pdf)
    if not pdf_path.is_file():
        sg.popup_error(f"Archivo no encontrado:\n{ruta_pdf}")
        return None
    
    try:
        # --- CARGAR PDF Y GENERAR MINIATURAS ---
        reader = PdfReader(pdf_path)
        total_paginas = len(reader.pages)
        
        if total_paginas == 0:
            sg.popup_error("El PDF no contiene páginas.")
            return None
        
        # Convertir cada página a imagen miniatura (150 DPI es suficiente para vista previa)
        # Usamos first_page/last_page para ser explícitos y evitar problemas con pdf2image
        imagenes_pil = convert_from_path(
            str(pdf_path),
            dpi=150,
            first_page=1,
            last_page=total_paginas,
            fmt='jpeg',  # Más pequeño que PNG para thumbnails
            jpegopt={"quality": 85}  # Balance calidad/tamaño
        )
        
        # Convertir PIL Images a bytes para PySimpleGUI (evita guardar archivos temporales)
        imagenes_bytes = []
        for img in imagenes_pil:
            buf = BytesIO()
            img.save(buf, format='JPEG')
            byte_im = buf.getvalue()
            imagenes_bytes.append(byte_im)
        
        # --- DISEÑO DE LA INTERFAZ ---
        sg.theme('LightGreen2')  # Tema suave y legible
        
        # Elementos de instrucción y estado
        texto_instruccion = [
            [sg.Text("Toque las páginas que necesita IMPRIMIR y FIRMAR físicamente:", 
                     font=("Helvetica", 16, "bold"))],
            [sg.Text(f"Documento: {pdf_path.name} | {total_paginas} páginas detectadas", 
                     font=("Helvetica", 10), text_color="gray")]
        ]
        
        # Grid de miniaturas (máximo 4 por fila para evitar ventana enorme)
        columnas_por_fila = 4
        filas_necesarias = (total_paginas + columnas_por_fila - 1) // columnas_por_fila
        
        elementos_grid = []
        for fila in range(filas_necesarias):
            fila_elementos = []
            for col in range(columnas_por_fila):
                indice_pagina = fila * columnas_por_fila + col
                if indice_pagina < total_paginas:
                    # Cada miniatura es un botón con imagen (para detectar clics)
                    fila_elementos.append(
                        sg.Button(
                            image_data=imagenes_bytes[indice_pagina],
                            key=f"-PAG-{indice_pagina}-",
                            button_color=("white", "#f0f0f0"),  # Blanco sobre gris claro
                            border_width=0,
                            size=(None, None),  # Ajusta al tamaño de la imagen
                            pad=(5, 5)  # Espacio entre miniaturas
                        )
                    )
                else:
                    # Rellenar celdas vacías para alineación
                    fila_elementos.append(sg.Text("", size=(1, 1)))
            elementos_grid.append(sg.Column([fila_elementos], pad=(0, 0)))
        
        # Panel de selección (con scroll para documentos largos)
        panel_seleccion = [
            [sg.Text("Páginas seleccionadas: ", font=("Helvetica", 12), key="-SEL-TEXTO-")],
            [sg.Text("", size=(40, 1), key="-SEL-LISTA-", font=("Courier", 10), 
                     background_color="#f8f9fa", relief="sunken", pad=(5, 5))]
        ]
        
        # Botones de acción
        botones_accion = [
            [sg.Button("SELECCIONAR TODAS", size=(15, 1), font=("Helvetica", 10)),
             sg.Button("DESSELECCIONAR TODAS", size=(15, 1), font=("Helvetica", 10))],
            [sg.Button("CANCELAR", size=(12, 1), button_color=("white", "#dc3545")),
             sg.Button("CONTINUAR", size=(12, 1), button_color=("white", "#28a745"), 
                       disabled=True)]  # Inicialmente deshabilitado hasta que haya selección
        ]
        
        # Layout completo
        layout = [
            [sg.Column(texto_instruccion, pad=(0, (10, 20)))],
            [sg.Column(elementos_grid, scrollable=True, vertical_scroll_only=True, 
                       size=(800, 500), pad=(0, 10))],
            [sg.Column(panel_seleccion, pad=(0, 10))],
            [sg.Column(botones_accion, element_justification="c", pad=(0, 20))]
        ]
        
        ventana = sg.Window(
            "Seleccionar Páginas para Firmar",
            layout,
            element_justification="c",
            finalize=True,
            keep_on_top=True,  # Siempre visible sobre otras ventanas
            return_keyboard_events=True  # Para detectar ESC/Enter si es necesario
        )
        
        # --- ESTADO INTERNO ---
        paginas_seleccionadas = set()  # Usamos set para evitar duplicados y búsqueda O(1)
        
        # --- BUCLE DE EVENTOS ---
        while True:
            evento, valores = ventana.read(timeout=100)  # Timeout pequeño para actualizar UI
            
            # Salir por cierre de ventana o tecla ESC
            if evento in (sg.WIN_CLOSED, "Cancelar", "CANCELAR", "Escape:27"):
                ventana.close()
                return None  # Señal de cancelación
            
            # Manejar clics en miniaturas
            if evento.startswith("-PAG-"):
                try:
                    indice_pagina = int(evento.split("-")[2])
                    if indice_pagina in paginas_seleccionadas:
                        # Deseleccionar: volver a estilo normal
                        ventana[evento].update(button_color=("white", "#f0f0f0"))
                        paginas_seleccionadas.remove(indice_pagina)
                    else:
                        # Seleccionar: resaltar con bordes rojos
                        ventana[evento].update(button_color=("white", "#ffc107"))  # Amarillo warning (más visible que rojo puro)
                        paginas_seleccionadas.add(indice_pagina)
                    
                    # Actualizar resumen de selección
                    if paginas_seleccionadas:
                        lista_ordenada = sorted(paginas_seleccionadas)
                        texto_resumen = ", ".join(str(p+1) for p in lista_ordenada)  # Mostrar 1-based al usuario
                        ventana["-SEL-TEXTO-"].update(f"Páginas seleccionadas: {len(paginas_seleccionadas)}")
                        ventana["-SEL-LISTA-"].update(texto_resumen)
                        ventana["CONTINUAR"].update(disabled=False)  # Habilitar botón
                    else:
                        ventana["-SEL-TEXTO-"].update("Ninguna página seleccionada")
                        ventana["-SEL-LISTA-"].update("")
                        ventana["CONTINUAR"].update(disabled=True)
                        
                except (ValueError, IndexError):
                    pass  # Ignorar eventos malformados
            
            # Botones de acción masiva
            if evento == "SELECCIONAR TODAS":
                for i in range(total_paginas):
                    if i not in paginas_seleccionadas:
                        ventana[f"-PAG-{i}-"].update(button_color=("white", "#ffc107"))
                paginas_seleccionadas = set(range(total_paginas))
                ventana["-SEL-TEXTO-"].update(f"Páginas seleccionadas: {total_paginas}")
                texto_resumen = ", ".join(str(p+1) for p in range(total_paginas))
                ventana["-SEL-LISTA-"].update(texto_resumen)
                ventana["CONTINUAR"].update(disabled=False)
                
            if evento == "DESSELECCIONAR TODAS":
                for i in range(total_paginas):
                    if i in paginas_seleccionadas:
                        ventana[f"-PAG-{i}-"].update(button_color=("white", "#f0f0f0"))
                paginas_seleccionadas.clear()
                ventana["-SEL-TEXTO-"].update("Ninguna página seleccionada")
                ventana["-SEL-LISTA-"].update("")
                ventana["CONTINUAR"].update(disabled=False)
            
            # Confirmar selección
            if evento == "CONTINUAR" and paginas_seleccionadas:
                ventana.close()
                return sorted(paginas_seleccionadas)  # Devolver lista ordenada 0-based
            
            # Atajos de teclado opcionales (útil para testing)
            if evento == "Return:13" and valores.get("-SEL-LISTA-", "") and not ventana["CONTINUAR"].get():
                ventana["CONTINUAR"].click()
                
    except Exception as e:
        sg.popup_error(f"Error al procesar el PDF:\n{str(e)}")
        print(f"[ERROR en seleccionar_paginas_pdf] {e}")  # Para depuración en consola
        return None

# ======================
# FASE 2: IMPRESIÓN Y ESPERA
# ======================
def fase2_impresion(pdf_path, paginas_seleccionadas):
    """
    Crea PDF temporal con solo las páginas seleccionadas y lo envía a imprimir.
    Espera confirmación del usuario de que imprimió físicamente.
    """
    # TODO: Implementar
    # 1. Usar PyPDF2 para extraer páginas seleccionadas a temp_print.pdf
    # 2. Enviar a impresora predeterminada (lp en Linux, win32print en Windows)
    # 3. Mostrar mensaje: "ESPERE A QUE IMPRIMA..." + botón "YA IMPRIMÍ, CONTINUAR"
    
    print(f"[FASE 2] Preparando impresión de páginas: {paginas_seleccionadas}")
    sg.popup("FASE 2 POR IMPLEMENTAR:\n"
             "Crear PDF con páginas seleccionadas y enviar a imprimir\n"
             "Esperar confirmación física de impresión")
    
    # Placeholder: simulamos que imprimió
    return True

# ======================
# FASE 3: ESCANEO Y REEMPLAZO
# ======================
def fase3_escaneo_reemplazo(pdf_original_path, paginas_seleccionadas, scans_folder):
    """
    Espera escaneos en la carpeta scans/, los procesa y reemplaza
    las páginas correspondientes en el PDF original.
    Devuelve: ruta del PDF firmado listo para enviar
    """
    # TODO: Implementar
    # 1. Monitorear carpeta scans/ por nuevos TIFF/PDF (usar polling o watchdog)
    # 2. Para cada escaneado, convertir a PDF página
    # 3. Usar PyPDF2 para reemplazar páginas en documento original
    # 4. Mostrar progreso: "ESCANEANDO PÁGINA X DE Y"
    
    print(f"[FASE 3] Esperando escaneos para páginas: {paginas_seleccionadas}")
    sg.popup("FASE 3 POR IMPLEMENTAR:\n"
             "Monitorear carpeta de escaneos, procesar imágenes y reemplazar páginas\n"
             "(Usaremos subprocess para scanimage o monitoreo de carpeta)")
    
    # Placeholder: devolvemos el original (en realidad sería el modificado)
    return pdf_original_path

# ======================
# FASE 4: CORREO Y RESUMEN
# ======================
def fase4_envio_email(pdf_firmado_path, config, resumen_paginas):
    """
    Pide al usuario el correo de destino, muestra resumen y envía el PDF.
    """
    # TODO: Implementar
    # 1. Ventana con campo enorme para correo y botón "ENVIAR DOCUMENTO"
    # 2. Validar formato de correo mientras escribe
    # 3. Mostrar resumen dinámico: "Se enviará: [nombre].pdf\nPáginas: X,Y,Z\nPara: [correo]"
    # 4. Enviar con yagmail/smtplib usando credenciales de config
    
    print(f"[FASE 4] Preparando envío de: {pdf_firmado_path}")
    sg.popup("FASE 4 POR IMPLEMENTAR:\n"
             "Solicitar correo, mostrar resumen y enviar PDF\n"
             "(Usaremos yagmail para envío sencillo)")

# ======================
# FLUJO PRINCIPAL DE LA APLICACIÓN
# ======================
def main():
    # Configuración inicial
    base_dir = setup_directories()
    config = load_config()
    
    # Tema de PySimpleGUI (suave para vista cansada)
    sg.theme('LightGreen2')  # Puedes probar otros temas: 'LightBlue2', 'GreenMono', etc.
    
    # Bucle principal: permite procesar múltiples documentos sin reiniciar
    while True:
        # --- PANTALLA DE INICIO: SELECCIÓN DE DOCUMENTO ---
        documentos_dir = base_dir / config["documents_folder"]
        pdf_files = list(documentos_dir.glob("*.pdf"))
        
        if not pdf_files:
            sg.popup_error(f"No se encontraron PDFs en:\n{documentos_dir}\n"
                           "Por favor coloque al menos un PDF original en esa carpeta.")
            break  # Salimos si no hay documentos para trabajar
        
        # Selección de documento (lista simple)
        doc_layout = [
            [sg.Text("Seleccione el documento PDF que necesita firmar:", font=("Helvetica", 14))],
            [sg.Listbox(
                values=[f.name for f in pdf_files],
                size=(40, min(10, len(pdf_files))),
                key="-DOC-LIST-",
                enable_events=True
            )],
            [sg.Button("SALIR", size=(10, 1)), sg.Button("CONTINUAR", size=(10, 1), button_color=('white', '#007BFF'))]
        ]
        
        doc_window = sg.Window("Asistente de Firmas Legales", doc_layout, element_justification='c')
        
        selected_doc = None
        while True:
            event, values = doc_window.read()
            if event in (sg.WIN_CLOSED, "SALIR"):
                doc_window.close()
                return  # Sale completamente de la app
            if event == "-DOC-LIST-" and values["-DOC-LIST-"]:
                selected_doc = documentos_dir / values["-DOC-LIST-"][0]
            if event == "CONTINUAR" and selected_doc:
                break
        doc_window.close()
        
        # --- EJECUTAR FASES SECUENCIALMENTE ---
        try:
            # FASE 1: Seleccionar páginas
            paginas_a_procesar = fase1_seleccion_paginas(selected_doc)
            if not paginas_a_procesar:  # Usuario canceló o no seleccionó nada
                sg.popup("No se seleccionaron páginas. Volviendo a inicio...")
                continue
            
            # FASE 2: Imprimir y esperar
            if not fase2_impresion(selected_doc, paginas_a_procesar):
                sg.popup_error("Error en fase de impresión. Volviendo a inicio...")
                continue
            
            # FASE 3: Escanear y reemplazar
            pdf_firmado = fase3_escaneo_reemplazo(
                selected_doc, 
                paginas_a_procesar, 
                base_dir / config["scans_folder"]
            )
            
            # FASE 4: Enviar por email
            fase4_envio_email(
                pdf_firmado, 
                config, 
                [p+1 for p in paginas_a_procesar]  # Convertimos a 1-based para mostrar al usuario
            )
            
            sg.popup("¡Flujos completado!\n"
                     "El documento ha sido procesado y enviado.\n"
                     "¿Desea procesar otro documento?",
                     title="Éxito")
                     
        except Exception as e:
            sg.popup_error(f"Error inesperado:\n{str(e)}\n"
                           "Revise la consola para más detalles.")
            print(f"Error en flujo principal: {e}")  # Para depuración

if __name__ == "__main__":
    main()