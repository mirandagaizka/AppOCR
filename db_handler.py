"""
Capa de persistencia.
- PostgreSQL cuando DATABASE_URL está definido (Render, Neon.tech, etc.)
- SQLite cuando no lo está (desarrollo local sin dependencias externas)
"""

import os
import sqlite3
import logging
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ─── Schema ──────────────────────────────────────────────────────────────────
_CREATE_PG = """
CREATE TABLE IF NOT EXISTS facturas (
    id               SERIAL PRIMARY KEY,
    timestamp        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    numero_factura   TEXT,
    fecha_factura    TEXT,
    fecha_vencimiento TEXT,
    emisor_nombre    TEXT,
    emisor_nif       TEXT,
    emisor_direccion TEXT,
    receptor_nombre  TEXT,
    receptor_nif     TEXT,
    receptor_direccion TEXT,
    concepto         TEXT,
    base_imponible   NUMERIC(14,2),
    porcentaje_iva   NUMERIC(6,2),
    cuota_iva        NUMERIC(14,2),
    total            NUMERIC(14,2),
    forma_pago       TEXT,
    iban             TEXT,
    moneda           TEXT DEFAULT 'EUR'
);
"""

_CREATE_SQLITE = _CREATE_PG.replace("SERIAL", "INTEGER").replace(
    "TIMESTAMPTZ", "TEXT"
).replace("NUMERIC(14,2)", "REAL").replace("NUMERIC(6,2)", "REAL")

_INSERT = """
INSERT INTO facturas (
    numero_factura, fecha_factura, fecha_vencimiento,
    emisor_nombre, emisor_nif, emisor_direccion,
    receptor_nombre, receptor_nif, receptor_direccion,
    concepto, base_imponible, porcentaje_iva, cuota_iva,
    total, forma_pago, iban, moneda
) VALUES (
    {ph}numero_factura{c} {ph}fecha_factura{c} {ph}fecha_vencimiento{c}
    {ph}emisor_nombre{c} {ph}emisor_nif{c} {ph}emisor_direccion{c}
    {ph}receptor_nombre{c} {ph}receptor_nif{c} {ph}receptor_direccion{c}
    {ph}concepto{c} {ph}base_imponible{c} {ph}porcentaje_iva{c} {ph}cuota_iva{c}
    {ph}total{c} {ph}forma_pago{c} {ph}iban{c} {ph}moneda{c_last}
)
"""

_COLS = [
    "id", "timestamp", "numero_factura", "fecha_factura", "fecha_vencimiento",
    "emisor_nombre", "emisor_nif", "emisor_direccion",
    "receptor_nombre", "receptor_nif", "receptor_direccion",
    "concepto", "base_imponible", "porcentaje_iva", "cuota_iva",
    "total", "forma_pago", "iban", "moneda",
]

_DATA_KEYS = [
    "numero_factura", "fecha_factura", "fecha_vencimiento",
    "emisor_nombre", "emisor_nif", "emisor_direccion",
    "receptor_nombre", "receptor_nif", "receptor_direccion",
    "concepto", "base_imponible", "porcentaje_iva", "cuota_iva",
    "total", "forma_pago", "iban", "moneda",
]


# ─── Backend selector ─────────────────────────────────────────────────────────

def _is_pg() -> bool:
    return bool(DATABASE_URL) and DATABASE_URL.startswith(("postgres", "postgresql"))


def _pg_conn():
    import psycopg2
    import psycopg2.extras
    return psycopg2.connect(DATABASE_URL)


def _sqlite_path() -> str:
    path = os.getenv("DATA_DIR", "data")
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, "facturas.db")


# ─── Public API ───────────────────────────────────────────────────────────────

def init_db() -> None:
    """Crea la tabla si no existe."""
    if _is_pg():
        conn = _pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(_CREATE_PG)
            conn.commit()
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(_sqlite_path())
        try:
            conn.execute(_CREATE_SQLITE)
            conn.commit()
        finally:
            conn.close()
    logger.info("DB inicializada (%s)", "PostgreSQL" if _is_pg() else "SQLite")


def insert_invoice(data: dict) -> int:
    """Inserta una factura. Devuelve el ID asignado."""
    row = {k: data.get(k) for k in _DATA_KEYS}
    # Convertir Decimal a float por si acaso
    for k in ("base_imponible", "porcentaje_iva", "cuota_iva", "total"):
        if isinstance(row.get(k), Decimal):
            row[k] = float(row[k])

    if _is_pg():
        import psycopg2.extras
        keys = list(row.keys())
        placeholders = ", ".join(f"%({k})s" for k in keys)
        sql = f"INSERT INTO facturas ({', '.join(keys)}) VALUES ({placeholders}) RETURNING id"
        conn = _pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, row)
                new_id = cur.fetchone()[0]
            conn.commit()
        finally:
            conn.close()
        return new_id
    else:
        # SQLite: también guarda el timestamp aquí
        row_sqlite = {**row, "timestamp": datetime.now().isoformat(sep=" ", timespec="seconds")}
        keys = list(row_sqlite.keys())
        placeholders = ", ".join("?" * len(keys))
        values = [row_sqlite[k] for k in keys]
        sql = f"INSERT INTO facturas ({', '.join(keys)}) VALUES ({placeholders})"
        conn = sqlite3.connect(_sqlite_path())
        try:
            cur = conn.execute(sql, values)
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def get_all_invoices() -> list[dict]:
    """Devuelve todas las facturas ordenadas por timestamp ASC."""
    if _is_pg():
        import psycopg2.extras
        conn = _pg_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM facturas ORDER BY timestamp ASC")
                rows = cur.fetchall()
        finally:
            conn.close()
        result = []
        for r in rows:
            d = dict(r)
            # Serializar tipos no-JSON
            for k, v in d.items():
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
                elif isinstance(v, Decimal):
                    d[k] = float(v)
            result.append(d)
        return result
    else:
        conn = sqlite3.connect(_sqlite_path())
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM facturas ORDER BY timestamp ASC").fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
