from io import BytesIO
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader

import requests
try:
    import streamlit as st  # disponible en la app
except Exception:
    st = None  # por si se ejecuta fuera de Streamlit

from utils import format_cop, ym_to_label


def build_invoice_pdf(datos):
    """
    datos:
      - cliente: {name, phone, payment_method, account, note}
      - year, month
      - clases: list[{fecha_str, hora_str, valor_int}]
      - total_int
      - hoy_str
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    W, H = LETTER
    margin = 18 * mm
    x = margin
    y = H - margin

    # ---------- Logo (opcional desde secrets) ----------
    logo_url = ""
    if st is not None:
        try:
            logo_url = st.secrets.get("APP_LOGO_URL", "")
        except Exception:
            logo_url = ""

    if logo_url:
        try:
            resp = requests.get(logo_url, timeout=10)
            resp.raise_for_status()
            img = ImageReader(BytesIO(resp.content))
            c.drawImage(img, x, y - 20 * mm, width=30 * mm, height=15 * mm, mask="auto")
        except Exception:
            c.setFillColor(colors.lightgrey)
            c.rect(x, y - 20 * mm, 30 * mm, 15 * mm, fill=1, stroke=0)
    else:
        c.setFillColor(colors.lightgrey)
        c.rect(x, y - 20 * mm, 30 * mm, 15 * mm, fill=1, stroke=0)

    # Emisor (opcional)
    emisor = ""
    if st is not None:
        try:
            emisor = st.secrets.get("EMISOR_NOMBRE", "")
        except Exception:
            emisor = ""

    if emisor:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x, y - 22 * mm, emisor)

    # Título y cabecera derecha
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 16)
    c.drawRightString(W - margin, y - 5 * mm, "Cuenta de cobro")

    c.setFont("Helvetica", 10)
    c.drawRightString(W - margin, y - 12 * mm, f"Fecha: {datos['hoy_str']}")
    c.drawRightString(W - margin, y - 17 * mm, f"Periodo: {ym_to_label(datos['year'], datos['month'])}")

    # ---------- Info cliente ----------
    y -= 28 * mm
    styles = getSampleStyleSheet()
    pstyle = ParagraphStyle(
        "small",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=12,
    )
    info_lines = [
        f"<b>Cliente:</b> {datos['cliente']['name']}",
        f"<b>Teléfono:</b> {datos['cliente'].get('phone','') or '-'}",
        f"<b>Método de pago:</b> {datos['cliente'].get('payment_method','') or '-'}",
        f"<b>Cuenta/Alias:</b> {datos['cliente'].get('account','') or '-'}",
    ]
    info_paragraphs = [[Paragraph(line, pstyle)] for line in info_lines]
    info_table = Table(info_paragraphs, colWidths=[W - 2 * margin])
    info_table.wrapOn(c, W, H)
    info_table.drawOn(c, x, y - 50)
    y -= 70

    # ---------- Tabla de ítems ----------
    encabezados = ["Fecha", "Hora", "Valor"]
    data = [encabezados]
    for item in datos["clases"]:
        data.append([item["fecha_str"], item["hora_str"], format_cop(item["valor_int"])])

    items_table = Table(
        data,
        colWidths=[(W - 2 * margin) * 0.4, (W - 2 * margin) * 0.3, (W - 2 * margin) * 0.3],
    )
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F0F0")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FBFBFB")]),
            ]
        )
    )
    items_table.wrapOn(c, W, H)
    items_table.drawOn(c, x, y - 18 * len(data))
    y = y - 18 * len(data) - 24

    # ---------- Total ----------
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(W - margin, y, f"Total: {format_cop(datos['total_int'])}")

    # Nota final opcional
    nota = ""
    if st is not None:
        try:
            nota = st.secrets.get("EMISOR_NOTA", "")
        except Exception:
            nota = ""
    if nota:
        c.setFont("Helvetica", 9)
        c.drawString(x, y - 12, nota[:120])

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
