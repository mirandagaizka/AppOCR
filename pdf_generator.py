from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable,
)
from reportlab.lib.enums import TA_CENTER
from datetime import datetime

BLUE_DARK  = colors.HexColor("#1F4E79")
BLUE_LIGHT = colors.HexColor("#D6E4F0")
BLUE_MID   = colors.HexColor("#AEC6CF")
GRAY       = colors.HexColor("#555555")
W          = 16.5 * cm


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("T", parent=base["Normal"],
            fontSize=20, fontName="Helvetica-Bold",
            textColor=BLUE_DARK, alignment=TA_CENTER, spaceAfter=4),
        "sub": ParagraphStyle("S", parent=base["Normal"],
            fontSize=9, textColor=GRAY, alignment=TA_CENTER, spaceAfter=16),
        "normal": ParagraphStyle("N", parent=base["Normal"], fontSize=9),
        "bold": ParagraphStyle("B", parent=base["Normal"], fontSize=9, fontName="Helvetica-Bold"),
        "small": ParagraphStyle("Sm", parent=base["Normal"], fontSize=8, textColor=GRAY),
        "white_bold": ParagraphStyle("WB", parent=base["Normal"],
            fontSize=9, fontName="Helvetica-Bold", textColor=colors.white),
    }


def _fmt(val, moneda: str = "EUR") -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):,.2f} {moneda}"
    except (TypeError, ValueError):
        return str(val)


def _section_bar(title: str, st: dict) -> Table:
    t = Table([[Paragraph(title, st["white_bold"])]], colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLUE_DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _kv_table(rows: list[list], col_widths: list) -> Table:
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), BLUE_LIGHT),
        ("TEXTCOLOR", (0, 0), (0, -1), BLUE_DARK),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOX", (0, 0), (-1, -1), 0.5, BLUE_MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BLUE_MID),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def generate_invoice_pdf(data: dict, output_path: str) -> str:
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )
    st = _styles()
    moneda = data.get("moneda") or "EUR"

    def v(key: str) -> str:
        val = data.get(key)
        return str(val) if val is not None else "—"

    content = []

    # Cabecera
    content.append(Paragraph("FACTURA ESCANEADA", st["title"]))
    content.append(Paragraph(
        f"Registrada el {datetime.now().strftime('%d/%m/%Y a las %H:%M')}",
        st["sub"],
    ))
    content.append(HRFlowable(width=W, thickness=2, color=BLUE_DARK))
    content.append(Spacer(1, 10))

    # Barra: número + fechas
    bar_data = [[
        [Paragraph("N° FACTURA", st["small"]), Paragraph(v("numero_factura"), st["bold"])],
        [Paragraph("FECHA FACTURA", st["small"]), Paragraph(v("fecha_factura"), st["bold"])],
        [Paragraph("VENCIMIENTO", st["small"]), Paragraph(v("fecha_vencimiento"), st["bold"])],
    ]]
    bar = Table(bar_data, colWidths=[5.5*cm, 5.5*cm, 5.5*cm])
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLUE_LIGHT),
        ("BOX", (0, 0), (-1, -1), 1, BLUE_DARK),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BLUE_MID),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    content.append(bar)
    content.append(Spacer(1, 12))

    # Emisor / Receptor en paralelo
    def party_cell(label: str, prefix: str) -> list:
        return [
            Paragraph(label, st["white_bold"]),
            Paragraph(v(f"{prefix}_nombre"), st["bold"]),
            Paragraph(f'NIF/CIF: {v(f"{prefix}_nif")}', st["small"]),
            Paragraph(v(f"{prefix}_direccion"), st["small"]),
        ]

    emisor_col  = party_cell("EMISOR", "emisor")
    receptor_col = party_cell("RECEPTOR", "receptor")

    def party_table(items: list, width: float) -> Table:
        rows = [[item] for item in items]
        t = Table(rows, colWidths=[width])
        styles_spec = [
            ("BACKGROUND", (0, 0), (-1, 0), BLUE_DARK),
            ("BACKGROUND", (0, 1), (-1, -1), BLUE_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, BLUE_MID),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        t.setStyle(TableStyle(styles_spec))
        return t

    parties = Table(
        [[party_table(emisor_col, 7.9*cm), party_table(receptor_col, 7.9*cm)]],
        colWidths=[8.25*cm, 8.25*cm],
    )
    parties.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
        ("INNERGRID", (0, 0), (-1, -1), 0, colors.white),
    ]))
    content.append(parties)
    content.append(Spacer(1, 12))

    # Concepto
    if data.get("concepto"):
        content.append(_section_bar("CONCEPTO", st))
        cq = Table([[v("concepto")]], colWidths=[W])
        cq.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, BLUE_MID),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        content.append(cq)
        content.append(Spacer(1, 8))

    # Importes
    content.append(_section_bar("IMPORTES", st))
    iva_pct  = data.get("porcentaje_iva")
    iva_cuo  = data.get("cuota_iva")
    iva_str  = "—"
    if iva_pct is not None and iva_cuo is not None:
        iva_str = f"{iva_pct}%  →  {_fmt(iva_cuo, moneda)}"
    elif iva_pct is not None:
        iva_str = f"{iva_pct}%"

    imp_data = [
        ["Base imponible", _fmt(data.get("base_imponible"), moneda)],
        ["IVA",            iva_str],
        ["TOTAL",          _fmt(data.get("total"), moneda)],
    ]
    imp = Table(imp_data, colWidths=[6*cm, 10.5*cm])
    imp.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), BLUE_DARK),
        ("BACKGROUND", (0, 0), (-1, -2), BLUE_LIGHT),
        ("BACKGROUND", (0, -1), (-1, -1), BLUE_DARK),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 13),
        ("BOX", (0, 0), (-1, -1), 1, BLUE_DARK),
        ("INNERGRID", (0, 0), (-1, -2), 0.5, BLUE_MID),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("RIGHTPADDING", (1, 0), (1, -1), 12),
    ]))
    content.append(imp)
    content.append(Spacer(1, 8))

    # Datos de pago
    pago_rows = []
    if data.get("forma_pago"):
        pago_rows.append(["Forma de pago", v("forma_pago")])
    if data.get("iban"):
        pago_rows.append(["IBAN", v("iban")])

    if pago_rows:
        content.append(_section_bar("DATOS DE PAGO", st))
        content.append(_kv_table(pago_rows, [4*cm, 12.5*cm]))

    doc.build(content)
    return output_path
