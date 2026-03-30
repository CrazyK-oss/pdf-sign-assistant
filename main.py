import sys, os, shutil, subprocess
from pathlib import Path
from dotenv import load_dotenv

# ── Bootstrap: instala dependencias si faltan ──────────────────────────────
def _instalar_deps():
    reqs = Path(__file__).parent / "requirements.txt"
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", str(reqs),
         "--no-warn-script-location", "--quiet"]
    )

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QFileDialog, QListWidget, QMessageBox,
        QLineEdit, QGroupBox, QStatusBar
    )
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
except ImportError:
    _instalar_deps()
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QFileDialog, QListWidget, QMessageBox,
        QLineEdit, QGroupBox, QStatusBar
    )
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont

import PyPDF2
import yagmail

load_dotenv(Path(__file__).parent / ".env")

BASE_DIR        = Path(__file__).parent
CARPETA_TRABAJO = BASE_DIR / "pdfs_trabajo"
CARPETA_FIRMADO = BASE_DIR / "pdfs_firmados"
CARPETA_TRABAJO.mkdir(exist_ok=True)
CARPETA_FIRMADO.mkdir(exist_ok=True)


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Sign Assistant")
        self.setMinimumSize(750, 580)
        self.pdfs = []
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # ── Sección: cargar PDFs ───────────────────────────────────────────
        grp_cargar = QGroupBox("📂  Documentos")
        lay_cargar = QVBoxLayout(grp_cargar)

        btn_buscar = QPushButton("Buscar PDFs…")
        btn_buscar.setFixedHeight(38)
        btn_buscar.clicked.connect(self.buscar_pdfs)
        lay_cargar.addWidget(btn_buscar)

        self.lista = QListWidget()
        self.lista.setMinimumHeight(140)
        lay_cargar.addWidget(self.lista)

        fila1 = QHBoxLayout()
        btn_firmar = QPushButton("✍️  Firmar seleccionado")
        btn_firmar.setFixedHeight(36)
        btn_firmar.clicked.connect(self.firmar_pdf)

        btn_limpiar = QPushButton("🗑️  Limpiar lista")
        btn_limpiar.setFixedHeight(36)
        btn_limpiar.clicked.connect(self.limpiar_lista)

        fila1.addWidget(btn_firmar)
        fila1.addWidget(btn_limpiar)
        lay_cargar.addLayout(fila1)
        root.addWidget(grp_cargar)

        # ── Sección: enviar por email ──────────────────────────────────────
        grp_email = QGroupBox("📧  Enviar por email")
        lay_email = QVBoxLayout(grp_email)

        fila2 = QHBoxLayout()
        fila2.addWidget(QLabel("Destinatario:"))
        self.inp_destinatario = QLineEdit()
        self.inp_destinatario.setPlaceholderText("correo@ejemplo.com")
        fila2.addWidget(self.inp_destinatario)
        lay_email.addLayout(fila2)

        fila3 = QHBoxLayout()
        fila3.addWidget(QLabel("Asunto:"))
        self.inp_asunto = QLineEdit("Documento firmado")
        fila3.addWidget(self.inp_asunto)
        lay_email.addLayout(fila3)

        btn_enviar = QPushButton("📤  Enviar PDF firmado seleccionado")
        btn_enviar.setFixedHeight(38)
        btn_enviar.clicked.connect(self.enviar_email)
        lay_email.addWidget(btn_enviar)

        lbl_nota = QLabel(
            "Credenciales en <b>.env</b> (EMAIL_REMITENTE / EMAIL_PASSWORD)"
        )
        lbl_nota.setStyleSheet("color: gray; font-size: 11px;")
        lay_email.addWidget(lbl_nota)
        root.addWidget(grp_email)

        # ── Status bar ────────────────────────────────────────────────────
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Listo.")

    # ── Acciones ──────────────────────────────────────────────────────────

    def buscar_pdfs(self):
        rutas, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar PDFs",
            str(Path.home()), "Archivos PDF (*.pdf)"
        )
        if not rutas:
            return
        for ruta_str in rutas:
            origen  = Path(ruta_str)
            destino = CARPETA_TRABAJO / origen.name
            if destino.exists():
                destino = CARPETA_TRABAJO / f"{origen.stem}_copia{origen.suffix}"
            shutil.copy2(origen, destino)
            self.pdfs.append(destino)
            self.lista.addItem(str(destino))
        self.status.showMessage(f"{len(rutas)} PDF(s) cargado(s) en carpeta de trabajo.")

    def firmar_pdf(self):
        item = self.lista.currentItem()
        if not item:
            QMessageBox.warning(self, "Aviso", "Selecciona un PDF de la lista.")
            return
        ruta_origen = Path(item.text())
        ruta_salida = CARPETA_FIRMADO / f"{ruta_origen.stem}_firmado.pdf"

        try:
            lector  = PyPDF2.PdfReader(str(ruta_origen))
            escritor = PyPDF2.PdfWriter()
            for pagina in lector.pages:
                escritor.add_page(pagina)
            escritor.add_metadata({
                "/Firmado":  "Sí",
                "/Firmante": "PDF Sign Assistant",
            })
            with open(ruta_salida, "wb") as f:
                escritor.write(f)
            self.status.showMessage(f"✅  Firmado guardado: {ruta_salida.name}")
            QMessageBox.information(
                self, "Firmado", f"PDF firmado guardado en:\n{ruta_salida}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error al firmar", str(e))

    def enviar_email(self):
        item = self.lista.currentItem()
        if not item:
            QMessageBox.warning(self, "Aviso", "Selecciona un PDF de la lista.")
            return

        destinatario = self.inp_destinatario.text().strip()
        asunto       = self.inp_asunto.text().strip() or "Documento firmado"
        if not destinatario:
            QMessageBox.warning(self, "Aviso", "Ingresa el correo destinatario.")
            return

        ruta_pdf = Path(item.text())
        # Busca la versión firmada si existe
        firmado = CARPETA_FIRMADO / f"{ruta_pdf.stem}_firmado.pdf"
        adjunto = str(firmado) if firmado.exists() else str(ruta_pdf)

        remitente = os.getenv("EMAIL_REMITENTE", "")
        password  = os.getenv("EMAIL_PASSWORD", "")
        if not remitente or not password:
            QMessageBox.critical(
                self, "Error de configuración",
                "Falta EMAIL_REMITENTE o EMAIL_PASSWORD en el archivo .env"
            )
            return

        try:
            yag = yagmail.SMTP(remitente, password)
            yag.send(
                to=destinatario,
                subject=asunto,
                contents=f"Adjunto el documento: {Path(adjunto).name}",
                attachments=adjunto,
            )
            self.status.showMessage(f"✅  Email enviado a {destinatario}")
            QMessageBox.information(self, "Enviado", f"Email enviado a {destinatario}")
        except Exception as e:
            QMessageBox.critical(self, "Error al enviar", str(e))

    def limpiar_lista(self):
        self.lista.clear()
        self.pdfs.clear()
        self.status.showMessage("Lista limpiada.")


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    ventana = VentanaPrincipal()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()