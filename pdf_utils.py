from io import BytesIO
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle

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
    margin = 18*mm
    x = margin
    y = H - margin

    # "Logo" genérico (un rectángulo)
    c.setFillColor(colors.lightgrey)
    c.rect(x, y-20*mm, 30*mm, 15*mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x+4*mm, y-12*mm, "LOGO")

    # Título
    c.setFont("Helvetica-Bold", 16)
    c.drawRightString(W-margin, y-5*mm, "Cuenta de cobro")

    # Encabezado derecha
    c.setFont("Helvetica", 10)
    c.drawRightString(W-margin, y-12*mm, f"Fecha: {datos['hoy_str']}")
    c.drawRightString(W-margin, y-17*mm, f"Periodo: {ym_to_label(datos['year'], datos['month'])}")

    # Info cliente
    y -= 28*mm
    styles = getSampleStyleSheet()
    pstyle = ParagraphStyle("small", parent=styles["Normal"], fontName="Helvetica", fontSize=10, leading=12)
    info = [
        f"<b>Cliente:</b> {datos['cliente']['name']}",
        f"<b>Teléfono:</b> {datos['cliente'].get('phone','') or '-'}",
        f"<b>Método de pago:</b> {datos['cliente'].get('payment_method','') or '-'}",
        f"<b>Cuenta/Alias:</b> {datos['cliente'].get('account','') or '-'}",
    ]
    text_obj = []
    for line in info:
        text_obj.append(Paragraph(line, pstyle))
    # Render como mini tabla
    t = Table([[text_obj[0]], [text_obj[1]], [text_obj[2]], [text_obj[3]]], colWidths=[W-2*margin])
    t.wrapOn(c, W, H)
    t.drawOn(c, x, y-50)
    y -= 70

    # Tabla de ítems
    encabezados = ["Fecha", "Hora", "Valor"]
    data = [encabezados]
    for item in datos["clases"]:
        data.append([item["fecha_str"], item["hora_str"], format_cop(item["valor_int"])])

    table = Table(data, colWidths=[(W-2*margin)*0.4, (W-2*margin)*0.3, (W-2*margin)*0.3])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#F0F0F0")),
        ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("ALIGN", (0,0), (-1,0), "CENTER"),
        ("ALIGN", (2,1), (2,-1), "RIGHT"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#FBFBFB")]),
    ]))
    table.wrapOn(c, W, H)
    table.drawOn(c, x, y-18*len(data))
    y = y - 18*len(data) - 24

    # Total
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(W-margin, y, f"Total: {format_cop(datos['total_int'])}")

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
