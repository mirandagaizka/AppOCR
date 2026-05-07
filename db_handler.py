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
    file_hash        TEXT,
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

# Migraciones idempotentes — añade columnas a tablas existentes sin perder datos
_MIGRATIONS_PG = [
    "ALTER TABLE facturas ADD COLUMN IF NOT EXISTS file_hash TEXT",
]
_MIGRATIONS_SQLITE = [
    "ALTER TABLE facturas ADD COLUMN file_hash TEXT",
]

_CREATE_SQLITE = (
    _CREATE_PG
    .replace("SERIAL", "INTEGER")
    .replace("TIMESTAMPTZ", "TEXT")
    .replace("DEFAULT NOW()", "DEFAULT CURRENT_TIMESTAMP")
    .replace("NUMERIC(14,2)", "REAL")
    .replace("NUMERIC(6,2)", "REAL")
)

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
    "id", "timestamp", "file_hash", "numero_factura", "fecha_factura", "fecha_vencimiento",
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

# Campos que insert_invoice acepta además de los de _DATA_KEYS
_INSERT_EXTRA_KEYS = ["file_hash"]


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
    """Crea la tabla si no existe y aplica migraciones idempotentes."""
    if _is_pg():
        conn = _pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(_CREATE_PG)
                for m in _MIGRATIONS_PG:
                    try:
                        cur.execute(m)
                    except Exception as exc:
                        logger.debug("Migración ignorada (%s): %s", m, exc)
            conn.commit()
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(_sqlite_path())
        try:
            conn.execute(_CREATE_SQLITE)
            # SQLite no tiene IF NOT EXISTS para columnas → comprobar antes
            existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(facturas)").fetchall()}
            for m in _MIGRATIONS_SQLITE:
                col_name = m.split("ADD COLUMN")[-1].strip().split()[0]
                if col_name not in existing_cols:
                    try:
                        conn.execute(m)
                    except Exception as exc:
                        logger.debug("Migración ignorada (%s): %s", m, exc)
            conn.commit()
        finally:
            conn.close()
    logger.info("DB inicializada (%s)", "PostgreSQL" if _is_pg() else "SQLite")


def find_duplicate(file_hash: str | None, emisor_nif: str | None,
                   numero_factura: str | None, fecha_factura: str | None) -> dict | None:
    """Busca una factura ya registrada que coincida por hash exacto o por
    tupla (emisor_nif, numero_factura, fecha_factura). Devuelve la fila o None."""
    if not file_hash and not (emisor_nif and numero_factura):
        return None

    conditions = []
    params: list = []
    placeholder = "%s" if _is_pg() else "?"

    if file_hash:
        conditions.append(f"file_hash = {placeholder}")
        params.append(file_hash)
    if emisor_nif and numero_factura:
        if fecha_factura:
            conditions.append(
                f"(emisor_nif = {placeholder} AND numero_factura = {placeholder} AND fecha_factura = {placeholder})"
            )
            params.extend([emisor_nif, numero_factura, fecha_factura])
        else:
            conditions.append(
                f"(emisor_nif = {placeholder} AND numero_factura = {placeholder})"
            )
            params.extend([emisor_nif, numero_factura])

    sql = f"SELECT * FROM facturas WHERE {' OR '.join(conditions)} ORDER BY id DESC LIMIT 1"

    if _is_pg():
        import psycopg2.extras
        conn = _pg_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                r = cur.fetchone()
        finally:
            conn.close()
        if r is None:
            return None
        d = dict(r)
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif isinstance(v, Decimal):
                d[k] = float(v)
        return d
    else:
        conn = sqlite3.connect(_sqlite_path())
        conn.row_factory = sqlite3.Row
        try:
            r = conn.execute(sql, params).fetchone()
        finally:
            conn.close()
        return dict(r) if r else None


def insert_invoice(data: dict) -> int:
    """Inserta una factura. Devuelve el ID asignado."""
    row = {k: data.get(k) for k in _DATA_KEYS}
    # file_hash y similares (extra) opcionales
    for k in _INSERT_EXTRA_KEYS:
        if data.get(k) is not None:
            row[k] = data[k]
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


def get_invoice(invoice_id: int) -> dict | None:
    """Devuelve una factura por id (o None)."""
    if _is_pg():
        import psycopg2.extras
        conn = _pg_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM facturas WHERE id = %s", (invoice_id,))
                r = cur.fetchone()
        finally:
            conn.close()
        if r is None:
            return None
        d = dict(r)
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif isinstance(v, Decimal):
                d[k] = float(v)
        return d
    else:
        conn = sqlite3.connect(_sqlite_path())
        conn.row_factory = sqlite3.Row
        try:
            r = conn.execute("SELECT * FROM facturas WHERE id = ?", (invoice_id,)).fetchone()
        finally:
            conn.close()
        return dict(r) if r else None


def update_invoice(invoice_id: int, data: dict) -> dict | None:
    """Actualiza los campos editables de una factura. Devuelve la fila actualizada."""
    row = {k: data.get(k) for k in _DATA_KEYS if k in data}
    if not row:
        return get_invoice(invoice_id)

    for k in ("base_imponible", "porcentaje_iva", "cuota_iva", "total"):
        if k in row and isinstance(row[k], Decimal):
            row[k] = float(row[k])

    if _is_pg():
        keys = list(row.keys())
        set_clause = ", ".join(f"{k} = %({k})s" for k in keys)
        sql = f"UPDATE facturas SET {set_clause} WHERE id = %(id)s"
        params = {**row, "id": invoice_id}
        conn = _pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()
        finally:
            conn.close()
    else:
        keys = list(row.keys())
        set_clause = ", ".join(f"{k} = ?" for k in keys)
        sql = f"UPDATE facturas SET {set_clause} WHERE id = ?"
        params = [row[k] for k in keys] + [invoice_id]
        conn = sqlite3.connect(_sqlite_path())
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    return get_invoice(invoice_id)


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
