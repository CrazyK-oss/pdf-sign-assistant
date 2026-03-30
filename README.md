# PDF Sign Assistant

> Desktop application built with Python + PyQt6 to automate the complete signing workflow for legal documents — designed for non-technical users with a clean, guided UI.

---

## Overview

**PDF Sign Assistant** streamlines the process of physically signing PDF documents and producing a digitally-updated copy. Instead of manually editing PDFs or managing scanned images, the app guides the user through a step-by-step flow: preview pages → print → scan → embed → save → send.

All interactions are handled from a single window with large, clearly labelled controls and real-time status feedback.

---

## Features

- 📄 **Page preview grid** — visualize all pages of a PDF before choosing which one to sign
- 🖨️ **Direct print** — sends a single page to the system printer automatically
- 🖼️ **Scan integration** — load or capture a scanned image of the signed page
- 🔄 **Page replacement** — embeds the scanned signature back into the original PDF at the correct position
- 💾 **Saved jobs list** — keeps a history of processed documents with timestamps; supports re-editing
- ✉️ **Email dispatch** — sends the signed document via SMTP directly from the app
- 🔒 **Safe cancellation** — cancel at any stage without corrupting the original file

---

## Workflow

```
Open PDF  →  Preview Pages  →  Print Page  →  Scan Signed Page  →  Save PDF  →  Send by Email
```

| Step | Module | Description |
|------|--------|-------------|
| 1 | `main.py` | Open a PDF and load it into the working session |
| 2 | `fase1_preview.py` | Display a scrollable grid of page thumbnails; select the target page |
| 3 | `fase2_print.py` | Send the selected page to the system printer |
| 4 | `fase3_scan.py` | Load the scanned/photographed signed page image |
| 5 | `fase_guardar.py` | Preview the result, confirm, and save the signed PDF |
| 6 | `fase4_email.py` | Send the final document via email using SMTP |

---

## Project Structure

```
pdf-sign-assistant/
├── main.py                  # Entry point · main window · workflow orchestration
├── config.json              # SMTP credentials and folder paths
├── config.example.env       # Environment variable template
├── requirements.txt         # Python dependencies
├── pdfs_trabajo/            # Temporary working copies (auto-created, gitignored)
├── pdfs_firmados/           # Final signed documents (auto-created, gitignored)
└── modules/
    ├── __init__.py
    ├── setup.py             # Folder setup and initialization helpers
    ├── fase1_preview.py     # Page thumbnail grid and selection
    ├── fase2_print.py       # System printer integration
    ├── fase3_scan.py        # Scan/image loading and preview
    ├── fase_guardar.py      # Page replacement and PDF save logic
    └── fase4_email.py       # SMTP email sending with PDF attachment
```

---

## Prerequisites

- **Python** 3.10 or higher
- **Poppler** — required by `pdf2image` for PDF rendering:
  - **Windows**: Download from [oschwartz10612/poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases/) and add the `bin/` folder to your system `PATH`
  - **Linux**: `sudo apt-get install poppler-utils`
  - **macOS**: `brew install poppler`
- **Compatible scanner** *(optional — images can also be loaded from disk)*:
  - Linux: `scanimage` via `sane-utils`
  - Windows: WIA (built-in, compatible with HP LaserJet MFP series)

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/CrazyK-oss/pdf-sign-assistant.git
cd pdf-sign-assistant

# 2. Create a virtual environment
python -m venv venv

# 3. Activate it
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux / macOS

# 4. Install dependencies
pip install -r requirements.txt
```

---

## Configuration

### `config.json` — SMTP & folder settings

Edit this file with your email credentials before running the app:

```json
{
    "email_user": "your_email@domain.com",
    "email_password": "your_app_password",
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "documents_folder": "./documents",
    "scans_folder": "./scans",
    "temp_folder": "./temp"
}
```

### `.env` — environment variable override *(optional)*

Copy `config.example.env` to `.env` and fill in your credentials:

```env
EMAIL_REMITENTE=your_email@domain.com
EMAIL_PASSWORD=your_app_password_here
```

> **Gmail users:** Use an *App Password*, not your regular account password.  
> Enable it at: **Google Account → Security → 2-Step Verification → App Passwords**

---

## Running the App

```bash
python main.py
```

The app auto-creates the `pdfs_trabajo/` and `pdfs_firmados/` directories on first launch. No additional setup required.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `PyQt6` | Desktop GUI framework |
| `pymupdf` | PDF parsing and page rendering |
| `Pillow` | Image processing and format conversion |
| `img2pdf` | Image-to-PDF conversion |
| `pypdf` | PDF manipulation (page replacement) |
| `reportlab` | PDF generation utilities |
| `watchdog` | Filesystem event monitoring |
| `pywin32` | Windows printer and WIA scanner integration |
| `python-dotenv` | `.env` file loading |

---

## Roadmap

Planned improvements for upcoming versions:

- [ ] **macOS support** — native printer and scanner integration via CUPS / ImageCapture
- [ ] **Multi-page signing** — select and process multiple pages in a single session
- [ ] **Batch document processing** — queue several PDFs and sign them sequentially
- [ ] **Digital signature support** — embed cryptographic signatures without physical printing
- [ ] **UI settings panel** — configure SMTP, default folders, and scanner from within the app
- [ ] **Export as ZIP** — bundle the signed PDF alongside its scanned images for archiving

---

## Technical Notes

- Only **one PDF** can be in progress at a time; the "Open PDF" button disables until the current session is closed or completed.
- Working copies are stored in `pdfs_trabajo/` and cleaned up automatically after saving or cancelling.
- Signed documents are persisted in `pdfs_firmados/` and listed in the main window with modification timestamps.
- Double-clicking a saved document reopens it for re-editing without modifying the original.
- All errors surface as user-friendly dialogs; detailed tracebacks are printed to the console for debugging.

---

## License

This project is private and not open for redistribution. All rights reserved.
