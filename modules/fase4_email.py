import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
import PySimpleGUI as sg


EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w{2,}$")


def _es_email_valido(email: str) -> bool:
    return bool(EMAIL_REGEX.match(email.strip()))


def _construir_resumen(nombre_doc: str, paginas: list[int]) -> str:
    nums = ", ".join(str(p + 1) for p in paginas)
    return (
        f"Documento:          {nombre_doc}\n"
        f"Páginas reemplazadas: {nums}\n"
        f"Total páginas firmadas: {len(paginas)}"
    )


def _enviar_smtp(config: dict, destinatario: str, pdf_path: Path, nombre_doc: str) -> bool:
    """Envía el PDF firmado por correo usando SMTP con las credenciales de config.json."""
    try:
        msg = MIMEMultipart()
        msg["From"] = config["email_user"]
        msg["To"] = destinatario
        msg["Subject"] = f"Documento Firmado: {nombre_doc}"

        cuerpo = (
            f"Estimado/a,\n\n"
            f"Adjunto encontrará el documento '{nombre_doc}' con las páginas firmadas.\n\n"
            f"Este correo fue generado automáticamente por el Asistente de Firmas Legales.\n"
        )
        msg.attach(MIMEText(cuerpo, "plain"))

        with open(pdf_path, "rb") as f:
            adjunto = MIMEBase("application", "octet-stream")
            adjunto.set_payload(f.read())
        encoders.encode_base64(adjunto)
        adjunto.add_header(
            "Content-Disposition",
            f"attachment; filename={pdf_path.name}",
        )
        msg.attach(adjunto)

        with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as servidor:
            servidor.ehlo()
            servidor.starttls()
            servidor.login(config["email_user"], config["email_password"])
            servidor.sendmail(config["email_user"], destinatario, msg.as_string())

        print(f"[FASE 4] Email enviado a: {destinatario}")
        return True
    except smtplib.SMTPAuthenticationError:
        sg.popup_error(
            "Error de autenticación de correo.\n"
            "Verifique las credenciales en config.json.\n"
            "(Para Gmail use una Contraseña de Aplicación, no su contraseña normal)"
        )
        return False
    except Exception as e:
        sg.popup_error(f"Error al enviar el correo:\n{e}")
        print(f"[ERROR fase4 smtp] {e}")
        return False


def enviar_documento(
    pdf_firmado: Path,
    config: dict,
    paginas: list[int],
    nombre_doc: str,
) -> None:
    """
    Muestra pantalla de resumen, solicita el correo del destinatario
    y envía el PDF firmado.

    Args:
        pdf_firmado: Path al PDF con todas las páginas ya reemplazadas.
        config:      Diccionario cargado desde config.json.
        paginas:     Lista de índices 0-based de páginas que se firmaron.
        nombre_doc:  Nombre del documento original (para asunto del correo).
    """
    resumen = _construir_resumen(nombre_doc, paginas)

    layout = [
        [sg.Text("✉️", font=("Helvetica", 48), justification="c")],
        [
            sg.Text(
                "Ingrese el correo del destinatario:",
                font=("Helvetica", 15, "bold"),
            )
        ],
        [
            sg.Input(
                key="-EMAIL-",
                font=("Helvetica", 14),
                size=(38, 1),
                focus=True,
            )
        ],
        [sg.Text("", key="-VALIDACION-", font=("Helvetica", 10), text_color="#dc3545")],
        [sg.HorizontalSeparator(pad=(0, 10))],
        [
            sg.Text(
                "Resumen del documento a enviar:",
                font=("Helvetica", 11, "bold"),
            )
        ],
        [
            sg.Multiline(
                resumen,
                size=(42, 4),
                disabled=True,
                font=("Courier", 10),
                background_color="#f8f9fa",
                no_scrollbar=True,
            )
        ],
        [sg.VPush()],
        [
            sg.Button(
                "CANCELAR",
                size=(12, 1),
                button_color=("white", "#dc3545"),
                font=("Helvetica", 11),
            ),
            sg.Button(
                "ENVIAR DOCUMENTO →",
                size=(20, 2),
                button_color=("white", "#28a745"),
                font=("Helvetica", 12, "bold"),
                key="-ENVIAR-",
                disabled=True,
            ),
        ],
    ]

    ventana = sg.Window(
        "Enviar Documento Firmado",
        layout,
        element_justification="c",
        size=(520, 460),
        finalize=True,
        return_keyboard_events=True,
    )

    while True:
        ev, vals = ventana.read(timeout=200)

        if ev in (sg.WIN_CLOSED, "CANCELAR"):
            ventana.close()
            return

        # Validar email en tiempo real mientras el usuario escribe
        email_actual = vals.get("-EMAIL-", "").strip()
        if email_actual:
            if _es_email_valido(email_actual):
                ventana["-VALIDACION-"].update("")  # Sin error
                ventana["-ENVIAR-"].update(disabled=False)
            else:
                ventana["-VALIDACION-"].update("Correo inválido (ejemplo: nombre@dominio.com)")
                ventana["-ENVIAR-"].update(disabled=True)
        else:
            ventana["-VALIDACION-"].update("")
            ventana["-ENVIAR-"].update(disabled=True)

        if ev == "-ENVIAR-" and _es_email_valido(email_actual):
            ventana["-ENVIAR-"].update("Enviando...", disabled=True)
            ventana.refresh()

            if _enviar_smtp(config, email_actual, pdf_firmado, nombre_doc):
                ventana.close()
                sg.popup(
                    "✅  ¡DOCUMENTO ENVIADO CORRECTAMENTE!",
                    f"\nDestinatario: {email_actual}\nDocumento: {nombre_doc}",
                    title="Envío exitoso",
                    font=("Helvetica", 13),
                )
            else:
                # Reactivar botón si falló para que pueda reintentar
                ventana["-ENVIAR-"].update("ENVIAR DOCUMENTO →", disabled=False)
