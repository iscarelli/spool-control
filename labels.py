import io
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from PIL import Image

PAGE_W = 60 * mm
PAGE_H = 40 * mm

QR_SIZE = 28 * mm
MARGIN = 3 * mm
TEXT_X = QR_SIZE + MARGIN * 2


def _make_qr_image(url: str) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def generate_label_pdf(spool: dict, filament: dict, base_url: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))

    url = f"{base_url.rstrip('/')}/spools/{spool['id']}"
    qr_img = _make_qr_image(url)

    qr_reader = ImageReader(qr_img)
    c.drawImage(qr_reader, MARGIN, PAGE_H - QR_SIZE - MARGIN, QR_SIZE, QR_SIZE)

    text_w = PAGE_W - TEXT_X - MARGIN
    y = PAGE_H - MARGIN

    brand = str(filament["brand"])
    material = str(filament["material"])
    family = str(filament["family"])
    spool_id = str(spool["id"])

    # Brand (small)
    c.setFont("Helvetica-Bold", 7)
    y -= 9
    c.drawString(TEXT_X, y, brand[:28])

    # Material (large, prominent)
    c.setFont("Helvetica-Bold", 15)
    y -= 15
    c.drawString(TEXT_X, y, material[:16])

    # Family/Color (wrapped at ~30 chars)
    c.setFont("Helvetica", 8)
    y -= 11
    if len(family) > 28:
        c.drawString(TEXT_X, y, family[:28])
        y -= 10
        c.drawString(TEXT_X, y, family[28:56])
    else:
        c.drawString(TEXT_X, y, family)

    # Separator line
    y -= 6
    c.setLineWidth(0.3)
    c.line(TEXT_X, y, PAGE_W - MARGIN, y)

    # Spool ID
    y -= 9
    c.setFont("Helvetica", 7)
    c.drawString(TEXT_X, y, f"ID: SP-{spool_id.zfill(4)}")

    c.save()
    return buf.getvalue()


def generate_multi_label_pdf(spools: list, base_url: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    for i, spool in enumerate(spools):
        if i > 0:
            c.showPage()
        url = f"{base_url.rstrip('/')}/spools/{spool['id']}"
        qr_img = _make_qr_image(url)
        qr_reader = ImageReader(qr_img)
        c.drawImage(qr_reader, MARGIN, PAGE_H - QR_SIZE - MARGIN, QR_SIZE, QR_SIZE)
        y = PAGE_H - MARGIN
        c.setFont("Helvetica-Bold", 7)
        y -= 9
        c.drawString(TEXT_X, y, str(spool.get("brand", ""))[:28])
        c.setFont("Helvetica-Bold", 15)
        y -= 15
        c.drawString(TEXT_X, y, str(spool.get("material", ""))[:16])
        family = str(spool.get("family", ""))
        c.setFont("Helvetica", 8)
        y -= 11
        if len(family) > 28:
            c.drawString(TEXT_X, y, family[:28])
            y -= 10
            c.drawString(TEXT_X, y, family[28:56])
        else:
            c.drawString(TEXT_X, y, family)
        y -= 6
        c.setLineWidth(0.3)
        c.line(TEXT_X, y, PAGE_W - MARGIN, y)
        y -= 9
        c.setFont("Helvetica", 7)
        c.drawString(TEXT_X, y, f"ID: SP-{str(spool['id']).zfill(4)}")
    c.save()
    return buf.getvalue()
