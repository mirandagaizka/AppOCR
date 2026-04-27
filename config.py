import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ACCESS_KEY = os.getenv("ACCESS_KEY", "")       # PIN de acceso (vacío = sin auth)
DATABASE_URL = os.getenv("DATABASE_URL", "")   # PostgreSQL en Render; vacío → SQLite local
DATA_DIR = os.getenv("DATA_DIR", "data")       # Para SQLite local y PDFs temporales
PDF_DIR = os.path.join(DATA_DIR, "pdfs")
