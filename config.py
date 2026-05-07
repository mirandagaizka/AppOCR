import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Modelo IA (Google Gemini) ───────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ─── Acceso y datos ──────────────────────────────────────────────────────────
ACCESS_KEY = os.getenv("ACCESS_KEY", "")       # PIN de acceso (vacío = sin auth)
DATABASE_URL = os.getenv("DATABASE_URL", "")   # PostgreSQL en Render; vacío → SQLite local
DATA_DIR = os.getenv("DATA_DIR", "data")       # Para SQLite local y PDFs temporales
PDF_DIR = os.path.join(DATA_DIR, "pdfs")
