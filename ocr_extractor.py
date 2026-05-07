import base64
import json
import re
import time
import logging
import mimetypes

from google import genai
from google.genai import types as genai_types

from config import GEMINI_API_KEY, GEMINI_MODEL

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

# Esquema de respuesta para forzar JSON estructurado en Gemini
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "numero_factura":     {"type": "STRING", "nullable": True},
        "fecha_factura":      {"type": "STRING", "nullable": True},
        "fecha_vencimiento":  {"type": "STRING", "nullable": True},
        "emisor_nombre":      {"type": "STRING", "nullable": True},
        "emisor_nif":         {"type": "STRING", "nullable": True},
        "emisor_direccion":   {"type": "STRING", "nullable": True},
        "receptor_nombre":    {"type": "STRING", "nullable": True},
        "receptor_nif":       {"type": "STRING", "nullable": True},
        "receptor_direccion": {"type": "STRING", "nullable": True},
        "concepto":           {"type": "STRING", "nullable": True},
        "base_imponible":     {"type": "NUMBER", "nullable": True},
        "porcentaje_iva":     {"type": "NUMBER", "nullable": True},
        "cuota_iva":          {"type": "NUMBER", "nullable": True},
        "total":              {"type": "NUMBER", "nullable": True},
        "forma_pago":         {"type": "STRING", "nullable": True},
        "iban":               {"type": "STRING", "nullable": True},
        "moneda":             {"type": "STRING", "nullable": True},
    },
    "required": SCHEMA_KEYS,
}


def _parse_json(text: str) -> dict:
    """Parsea texto que se supone JSON. Tolera markdown fences y JSON truncado por límite de tokens."""
    text = (text or "").strip()

    # Quitar fences ```json ... ```
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Buscar el bloque {...} más amplio
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Último recurso: si el JSON está truncado por max_tokens, cerrar llaves/corchetes pendientes
    if text.startswith("{"):
        opens_curly  = text.count("{") - text.count("}")
        opens_square = text.count("[") - text.count("]")
        # Quitar fragmento incompleto al final (coma colgando, valor a medias)
        cleaned = re.sub(r",\s*$", "", text)
        cleaned = re.sub(r":\s*[^,}\]]*$", ": null", cleaned)
        cleaned += "]" * max(0, opens_square)
        cleaned += "}" * max(0, opens_curly)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No se encontró JSON válido en la respuesta. Texto recibido ({len(text)} chars): {text[:1000]}")


def _normalize_mime(mime_type: str) -> str:
    if not mime_type:
        return "image/jpeg"
    if mime_type == "image/jpg":
        return "image/jpeg"
    return mime_type


def extract_invoice_data(image_path: str, mime_type: str = "image/jpeg") -> dict:
    """Extrae datos de factura desde imagen o PDF usando Gemini. Reintenta hasta 3 veces."""

    if not GEMINI_API_KEY:
        raise RuntimeError("Falta GEMINI_API_KEY en variables de entorno")

    mime_type = _normalize_mime(mime_type)

    with open(image_path, "rb") as f:
        file_bytes = f.read()

    client = genai.Client(api_key=GEMINI_API_KEY)

    file_part = genai_types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
    prompt_part = genai_types.Part.from_text(text=PROMPT)

    # Deshabilitar "thinking" si la versión del SDK lo soporta — la extracción de facturas
    # no necesita razonamiento previo y libera todo el presupuesto de tokens para el JSON.
    config_kwargs = dict(
        temperature=0,
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        max_output_tokens=8192,
    )
    try:
        config_kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_budget=0)
    except (AttributeError, TypeError):
        pass

    config = genai_types.GenerateContentConfig(**config_kwargs)

    last_error = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[file_part, prompt_part],
                config=config,
            )

            # Diagnóstico: por qué terminó la generación (STOP, MAX_TOKENS, SAFETY...)
            finish_reason = None
            try:
                finish_reason = response.candidates[0].finish_reason
            except (IndexError, AttributeError):
                pass

            # Vía 1: el SDK ya devuelve el objeto parseado cuando hay response_schema
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, dict) and parsed:
                result = parsed
            else:
                # Vía 2: parsear el .text manualmente
                text = ""
                if hasattr(response, "text") and response.text:
                    text = response.text
                else:
                    try:
                        text = response.candidates[0].content.parts[0].text or ""
                    except Exception:
                        pass

                if not text:
                    raise ValueError(f"Respuesta vacía de Gemini (finish_reason={finish_reason})")

                try:
                    result = _parse_json(text)
                except ValueError as ve:
                    logger.error("Texto crudo de Gemini (finish_reason=%s):\n%s", finish_reason, text)
                    raise ve

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
