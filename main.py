import sys
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QListWidget, QMessageBox
)
from PyQt6.QtCore import Qt

CARPETA_TRABAJO = Path(__file__).parent / "pdfs_trabajo"
CARPETA_TRABAJO.mkdir(exist_ok=True)


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Sign Assistant")
        self.setMinimumSize(700, 500)
        self.pdfs_cargados = []
        self._construir_ui()

    def _construir_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Botón buscar PDFs
        btn_buscar = QPushButton("📂  Buscar PDFs...")
        btn_buscar.setFixedHeight(40)
        btn_buscar.clicked.connect(self.buscar_pdfs)
        layout.addWidget(btn_buscar)

        # Lista de PDFs cargados
        self.lista = QListWidget()
        layout.addWidget(self.lista)

        # Etiqueta carpeta de trabajo
        self.lbl_carpeta = QLabel(f"Carpeta de trabajo: {CARPETA_TRABAJO}")
        self.lbl_carpeta.setWordWrap(True)
        layout.addWidget(self.lbl_carpeta)

        # Botones de acción
        fila_botones = QHBoxLayout()
        btn_firmar = QPushButton("✍️  Firmar seleccionado")
        btn_firmar.setFixedHeight(36)
        btn_firmar.clicked.connect(self.firmar_pdf)

        btn_limpiar = QPushButton("🗑️  Limpiar lista")
        btn_limpiar.setFixedHeight(36)
        btn_limpiar.clicked.connect(self.limpiar_lista)

        fila_botones.addWidget(btn_firmar)
        fila_botones.addWidget(btn_limpiar)
        layout.addLayout(fila_botones)

    def buscar_pdfs(self):
        """Abre diálogo para buscar PDFs desde cualquier ubicación."""
        rutas, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar PDFs",
            str(Path.home()),       # arranca en el home del usuario
            "Archivos PDF (*.pdf)"
        )
        if not rutas:
            return

        for ruta_str in rutas:
            origen = Path(ruta_str)
            destino = CARPETA_TRABAJO / origen.name

            # Evitar duplicados
            if destino.exists():
                destino = CARPETA_TRABAJO / f"{origen.stem}_copia{origen.suffix}"

            shutil.copy2(origen, destino)
            self.pdfs_cargados.append(destino)
            self.lista.addItem(str(destino))

    def firmar_pdf(self):
        """Procesa el PDF seleccionado en la lista."""
        item = self.lista.currentItem()
        if not item:
            QMessageBox.warning(self, "Aviso", "Selecciona un PDF de la lista primero.")
            return
        ruta = Path(item.text())
        # TODO: lógica de firma aquí
        QMessageBox.information(self, "OK", f"Firmando: {ruta.name}")

    def limpiar_lista(self):
        self.lista.clear()
        self.pdfs_cargados.clear()


def main():
    app = QApplication(sys.argv)
    ventana = VentanaPrincipal()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()