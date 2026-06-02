import io
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from PIL import Image


def _make_qr_image(url: str) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=10,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def _draw_label(c, spool: dict, base_url: str, page_w: float, page_h: float):
    """Draw one label on the current canvas page. Coordinates in ReportLab points."""
    margin = 3 * mm
    # QR fills 70% of height, capped so text area has room
    qr_size = min(page_h * 0.70, page_w * 0.42)
    text_x = qr_size + margin * 2

    # Scale fonts relative to the reference 40mm height
    scale = page_h / (40 * mm)
    f_brand    = max(5.0, 7.0  * scale)
    f_material = max(8.0, 15.0 * scale)
    f_family   = max(5.0, 8.0  * scale)
    f_id       = max(5.0, 7.0  * scale)

    url = f"{base_url.rstrip('/')}/spools/{spool['id']}"
    c.drawImage(ImageReader(_make_qr_image(url)),
                margin, page_h - qr_size - margin, qr_size, qr_size)

    y = page_h - margin
    brand    = str(spool.get("brand",    ""))[:28]
    material = str(spool.get("material", ""))[:16]
    family   = str(spool.get("family",   ""))
    sid      = str(spool["id"]).zfill(4)

    c.setFont("Helvetica-Bold", f_brand)
    y -= f_brand * 1.4
    c.drawString(text_x, y, brand)

    c.setFont("Helvetica-Bold", f_material)
    y -= f_material * 1.2
    c.drawString(text_x, y, material)

    c.setFont("Helvetica", f_family)
    y -= f_family * 1.4
    max_chars = max(12, int(28 * scale))
    if len(family) > max_chars:
        c.drawString(text_x, y, family[:max_chars])
        y -= f_family * 1.3
        c.drawString(text_x, y, family[max_chars: max_chars * 2])
    else:
        c.drawString(text_x, y, family)

    y -= 5 * scale
    c.setLineWidth(0.3)
    c.line(text_x, y, page_w - margin, y)

    c.setFont("Helvetica", f_id)
    y -= f_id * 1.4
    c.drawString(text_x, y, f"ID: SP-{sid}")


def generate_label_pdf(spool: dict, base_url: str,
                       width_mm: float = 60, height_mm: float = 40) -> bytes:
    page_w, page_h = width_mm * mm, height_mm * mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    _draw_label(c, spool, base_url, page_w, page_h)
    c.save()
    return buf.getvalue()


def generate_multi_label_pdf(spools: list, base_url: str,
                             width_mm: float = 60, height_mm: float = 40) -> bytes:
    page_w, page_h = width_mm * mm, height_mm * mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    for i, spool in enumerate(spools):
        if i > 0:
            c.showPage()
        _draw_label(c, spool, base_url, page_w, page_h)
    c.save()
    return buf.getvalue()
