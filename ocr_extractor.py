import anthropic
import base64
import json
import re
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_KEYS = [
    "numero_factura", "fecha_factura", "fecha_vencimiento",
    "emisor_nombre", "emisor_nif", "emisor_direccion",
    "receptor_nombre", "receptor_nif", "receptor_direccion",
    "concepto", "base_imponible", "porcentaje_iva", "cuota_iva",
    "total", "forma_pago", "iban", "moneda",
]

PROMPT = """Analiza este documento y extrae los datos de factura.
Devuelve ÚNICAMENTE un objeto JSON válido. Sin texto antes ni después.
Si un campo no existe o no es legible, usa null. No inventes datos.
Fechas en formato YYYY-MM-DD. Importes como número decimal (1234.56).

{
  "numero_factura": string|null,
  "fecha_factura": string|null,
  "fecha_vencimiento": string|null,
  "emisor_nombre": string|null,
  "emisor_nif": string|null,
  "emisor_direccion": string|null,
  "receptor_nombre": string|null,
  "receptor_nif": string|null,
  "receptor_direccion": string|null,
  "concepto": string|null,
  "base_imponible": number|null,
  "porcentaje_iva": number|null,
  "cuota_iva": number|null,
  "total": number|null,
  "forma_pago": string|null,
  "iban": string|null,
  "moneda": "EUR"
}"""


def _parse_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Extraer JSON aunque haya texto alrededor
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        return json.loads(match.group())
    raise ValueError(f"No se encontró JSON válido en la respuesta: {text[:300]}")


def extract_invoice_data(image_path: str, mime_type: str = "image/jpeg") -> dict:
    """Extrae datos de factura desde imagen o PDF. Reintenta hasta 3 veces."""

    with open(image_path, "rb") as f:
        encoded = base64.standard_b64encode(f.read()).decode("utf-8")

    if mime_type == "application/pdf":
        content_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": encoded},
        }
    else:
        # Normalizar MIME — Telegram a veces envía image/jpg
        if mime_type == "image/jpg":
            mime_type = "image/jpeg"
        content_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": mime_type, "data": encoded},
        }

    last_error = None
    for attempt in range(3):
        try:
            client = anthropic.Anthropic()
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [content_block, {"type": "text", "text": PROMPT}],
                }],
            )
            result = _parse_json(message.content[0].text)

            # Garantizar que todas las claves existen
            for key in SCHEMA_KEYS:
                if key not in result:
                    result[key] = None
            if not result.get("moneda"):
                result["moneda"] = "EUR"

            return result

        except Exception as exc:
            last_error = exc
            logger.warning("Intento %d/3 fallido: %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"OCR fallido tras 3 intentos: {last_error}")
