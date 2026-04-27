import os
import logging
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import ACCESS_KEY, PDF_DIR, DATA_DIR
from ocr_extractor import extract_invoice_data
from db_handler import init_db, insert_invoice, get_all_invoices
from excel_handler import generate_excel_bytes
from pdf_generator import generate_invoice_pdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

Path(PDF_DIR).mkdir(parents=True, exist_ok=True)
Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Invoice OCR", docs_url=None, redoc_url=None)

ALLOWED_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp", "application/pdf"}
MAX_SIZE = 20 * 1024 * 1024  # 20 MB


@app.on_event("startup")
async def startup():
    init_db()


# ─── Auth ────────────────────────────────────────────────────────────────────

def _check_auth(header_key: str | None, query_key: str | None = None):
    if not ACCESS_KEY:
        return
    if header_key == ACCESS_KEY or query_key == ACCESS_KEY:
        return
    raise HTTPException(status_code=401, detail="Clave de acceso incorrecta")


# ─── API ─────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/scan")
async def scan_invoice(
    file: UploadFile = File(...),
    x_access_key: str | None = Header(default=None),
):
    _check_auth(x_access_key)

    mime = file.content_type or "image/jpeg"
    if mime not in ALLOWED_MIME:
        raise HTTPException(400, f"Formato no soportado: {mime}")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "Archivo demasiado grande (máximo 20 MB)")

    ext = ".pdf" if mime == "application/pdf" else ".jpg"
    tmp_path = None

    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        logger.info("Procesando factura: %d bytes, tipo %s", len(content), mime)
        data = extract_invoice_data(tmp_path, mime)

        inv_id = insert_invoice(data)

        # PDF temporal — se genera al momento y se devuelve la URL para descarga inmediata
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        num = data.get("numero_factura") or "sin-numero"
        safe_num = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(num))
        pdf_name = f"factura_{safe_num}_{ts}.pdf"
        pdf_path = str(Path(PDF_DIR) / pdf_name)
        generate_invoice_pdf(data, pdf_path)

        logger.info("Factura registrada id=%d → %s", inv_id, pdf_name)
        return JSONResponse({
            "ok": True,
            "data": data,
            "pdf_url": f"/api/pdf/{pdf_name}",
            "id": inv_id,
        })

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error procesando factura", exc_info=True)
        raise HTTPException(500, f"Error al procesar la factura: {exc}") from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.get("/api/pdf/{filename}")
async def get_pdf(
    filename: str,
    x_access_key: str | None = Header(default=None),
    key: str | None = None,
):
    _check_auth(x_access_key, key)
    safe_name = Path(filename).name
    pdf_path = Path(PDF_DIR) / safe_name
    if not pdf_path.exists():
        raise HTTPException(404, "PDF no encontrado (puede haberse eliminado en un reinicio del servidor; re-escanea la factura)")
    return FileResponse(pdf_path, media_type="application/pdf", filename=safe_name)


@app.get("/api/excel")
async def get_excel(
    x_access_key: str | None = Header(default=None),
    key: str | None = None,
):
    _check_auth(x_access_key, key)
    invoices = get_all_invoices()
    if not invoices:
        raise HTTPException(404, "Todavía no hay facturas registradas")
    xlsx_bytes = generate_excel_bytes(invoices)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=facturas_registro.xlsx"},
    )


@app.get("/api/invoices")
async def list_invoices(
    x_access_key: str | None = Header(default=None),
    key: str | None = None,
):
    _check_auth(x_access_key, key)
    invoices = get_all_invoices()
    return JSONResponse({"count": len(invoices), "invoices": invoices})


# ─── Frontend (debe ir al final) ─────────────────────────────────────────────
app.mount("/", StaticFiles(directory="static", html=True), name="static")
