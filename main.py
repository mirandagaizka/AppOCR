import os
import io
import zipfile
import hashlib
import logging
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Body, Query
from fastapi.responses import FileResponse, Response, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import ACCESS_KEY, PDF_DIR, DATA_DIR
from ocr_extractor import extract_invoice_data
from db_handler import (
    init_db, insert_invoice, get_all_invoices, get_invoice,
    update_invoice, find_duplicate,
)
from excel_handler import generate_excel_bytes
from pdf_generator import generate_invoice_pdf

EDITABLE_KEYS = {
    "numero_factura", "fecha_factura", "fecha_vencimiento",
    "emisor_nombre", "emisor_nif", "emisor_direccion",
    "receptor_nombre", "receptor_nif", "receptor_direccion",
    "concepto", "base_imponible", "porcentaje_iva", "cuota_iva",
    "total", "forma_pago", "iban", "moneda",
}
NUMERIC_KEYS = {"base_imponible", "porcentaje_iva", "cuota_iva", "total"}


def _coerce_payload(payload: dict) -> dict:
    """Filtra solo campos editables y convierte numéricos a float."""
    clean = {}
    for k, v in payload.items():
        if k not in EDITABLE_KEYS:
            continue
        if v == "" or v is None:
            clean[k] = None
            continue
        if k in NUMERIC_KEYS:
            try:
                clean[k] = float(str(v).replace(",", "."))
            except (TypeError, ValueError):
                raise HTTPException(400, f"Campo '{k}' no es un número válido: {v}")
        else:
            clean[k] = str(v).strip() or None
    return clean


def _build_pdf(data: dict) -> str:
    """Genera el PDF y devuelve solo el nombre del archivo."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    num = data.get("numero_factura") or "sin-numero"
    safe_num = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(num))
    pdf_name = f"factura_{safe_num}_{ts}.pdf"
    pdf_path = str(Path(PDF_DIR) / pdf_name)
    generate_invoice_pdf(data, pdf_path)
    return pdf_name

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
    force: bool = Query(False, description="Forzar procesamiento aunque sea duplicado"),
    x_access_key: str | None = Header(default=None),
):
    _check_auth(x_access_key)

    mime = file.content_type or "image/jpeg"
    if mime not in ALLOWED_MIME:
        raise HTTPException(400, f"Formato no soportado: {mime}")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "Archivo demasiado grande (máximo 20 MB)")

    file_hash = hashlib.sha256(content).hexdigest()

    # Detección por hash exacto antes de gastar llamada a Gemini
    if not force:
        dup = find_duplicate(file_hash, None, None, None)
        if dup:
            logger.info("Duplicado por hash bloqueado (existe id=%s)", dup.get("id"))
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "duplicate": True,
                    "reason": "file_hash",
                    "message": "Este archivo ya ha sido procesado antes.",
                    "existing": dup,
                },
            )

    ext = ".pdf" if mime == "application/pdf" else ".jpg"
    tmp_path = None

    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        logger.info("Procesando factura: %d bytes, tipo %s, hash=%s", len(content), mime, file_hash[:12])
        data = extract_invoice_data(tmp_path, mime)

        # Detección por contenido: misma factura escaneada desde fuente distinta (foto vs PDF)
        if not force:
            dup = find_duplicate(
                None,
                data.get("emisor_nif"),
                data.get("numero_factura"),
                data.get("fecha_factura"),
            )
            if dup:
                logger.info("Duplicado por contenido bloqueado (existe id=%s)", dup.get("id"))
                return JSONResponse(
                    status_code=409,
                    content={
                        "ok": False,
                        "duplicate": True,
                        "reason": "contenido",
                        "message": "Ya existe una factura con el mismo emisor, número y fecha.",
                        "existing": dup,
                        "data": data,   # los datos extraídos por si el usuario quiere forzar
                    },
                )

        data["file_hash"] = file_hash
        inv_id = insert_invoice(data)
        pdf_name = _build_pdf(data)

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


@app.get("/api/invoices/{invoice_id}")
async def get_invoice_endpoint(
    invoice_id: int,
    x_access_key: str | None = Header(default=None),
):
    _check_auth(x_access_key)
    inv = get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Factura no encontrada")
    pdf_name = _build_pdf(inv)
    return JSONResponse({
        "ok": True,
        "data": inv,
        "pdf_url": f"/api/pdf/{pdf_name}",
        "id": invoice_id,
    })


@app.put("/api/invoices/{invoice_id}")
async def update_invoice_endpoint(
    invoice_id: int,
    payload: dict = Body(...),
    x_access_key: str | None = Header(default=None),
):
    _check_auth(x_access_key)

    existing = get_invoice(invoice_id)
    if not existing:
        raise HTTPException(404, "Factura no encontrada")

    clean = _coerce_payload(payload)
    if not clean:
        raise HTTPException(400, "No se recibieron campos válidos para actualizar")

    updated = update_invoice(invoice_id, clean)
    if not updated:
        raise HTTPException(500, "No se pudo actualizar la factura")

    pdf_name = _build_pdf(updated)
    logger.info("Factura id=%d actualizada → %s", invoice_id, pdf_name)

    return JSONResponse({
        "ok": True,
        "data": updated,
        "pdf_url": f"/api/pdf/{pdf_name}",
        "id": invoice_id,
    })


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


@app.post("/api/pdfs/zip")
async def get_pdfs_zip(
    payload: dict = Body(...),
    x_access_key: str | None = Header(default=None),
):
    """Empaqueta los PDFs de un conjunto de facturas en un ZIP.
    payload: {"ids": [1, 2, 3]}"""
    _check_auth(x_access_key)
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "Se requiere una lista de ids")

    buffer = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for inv_id in ids:
            try:
                inv_id_int = int(inv_id)
            except (TypeError, ValueError):
                continue
            inv = get_invoice(inv_id_int)
            if not inv:
                continue
            pdf_name = _build_pdf(inv)
            pdf_path = Path(PDF_DIR) / pdf_name
            if pdf_path.exists():
                zf.write(pdf_path, arcname=pdf_name)
                added += 1

    if added == 0:
        raise HTTPException(404, "No se pudo generar ningún PDF para los ids indicados")

    buffer.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"facturas_{ts}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
