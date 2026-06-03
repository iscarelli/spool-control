import io
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from PIL import Image, ImageDraw, ImageFont


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


# ── Render 1-bit PNG para impressão térmica direta (Niimbot via navegador) ────
# Mesma hierarquia visual do PDF (QR à esquerda, texto à direita), mas rasterizado
# em preto/branco puro no tamanho de pixels nativo da etiqueta. O navegador só
# faz o threshold e envia via Web Bluetooth (ver static/niimbot.js).

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Carrega uma TTF (DejaVu no LXC, Arial no Windows dev) com fallback."""
    if bold:
        candidates = ["DejaVuSans-Bold.ttf", "arialbd.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    else:
        candidates = ["DejaVuSans.ttf", "arial.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    try:
        return ImageFont.load_default(size)  # Pillow >= 10.1 (escalável)
    except TypeError:
        return ImageFont.load_default()


def _text_h(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text or "X", font=font)
    return bbox[3] - bbox[1]


def _wrap_to_width(draw, text: str, font, max_w: int, max_lines: int = 2) -> list:
    """Quebra `text` em até `max_lines` linhas que caibam em `max_w` pixels."""
    words = (text or "").split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines - 1:
                break
    if cur:
        lines.append(cur)
    # Trunca a última linha com reticências se ainda sobrou texto
    last = lines[-1] if lines else ""
    while lines and draw.textlength(last + "…", font=font) > max_w and len(last) > 1:
        last = last[:-1]
        lines[-1] = last
    consumed = sum(len(l.split()) for l in lines)
    if consumed < len(words):
        lines[-1] = (lines[-1] + "…")
    return lines[:max_lines]


def generate_label_png(spool: dict, base_url: str,
                       w_px: int = 584, h_px: int = 354) -> bytes:
    """Etiqueta 1-bit (preto/branco) no tamanho de pixels nativo da Niimbot."""
    img = Image.new("1", (w_px, h_px), 1)  # 1 = branco
    draw = ImageDraw.Draw(img)

    margin = max(4, round(h_px * 0.06))
    # QR ocupa ~70% da altura, limitado a ~42% da largura (igual ao PDF)
    qr_size = min(h_px - 2 * margin, round(w_px * 0.42))

    url = f"{base_url.rstrip('/')}/spools/{spool['id']}"
    qr = _make_qr_image(url).convert("1").resize((qr_size, qr_size), Image.NEAREST)
    img.paste(qr, (margin, margin))

    text_x = margin + qr_size + margin
    text_w = w_px - text_x - margin

    # Fontes proporcionais à altura (ratios derivados dos pontos do PDF @40mm)
    f_brand = _load_font(max(10, round(h_px * 0.065)), bold=True)
    f_material = _load_font(max(14, round(h_px * 0.135)), bold=True)
    f_family = _load_font(max(10, round(h_px * 0.075)))
    f_id = _load_font(max(10, round(h_px * 0.065)))

    brand = str(spool.get("brand", ""))[:28]
    material = str(spool.get("material", ""))[:16]
    family = str(spool.get("family", ""))
    sid = str(spool["id"]).zfill(4)

    gap = max(2, round(h_px * 0.02))
    y = margin

    draw.text((text_x, y), brand, font=f_brand, fill=0)
    y += _text_h(draw, brand, f_brand) + gap

    draw.text((text_x, y), material, font=f_material, fill=0)
    y += _text_h(draw, material, f_material) + gap

    for line in _wrap_to_width(draw, family, f_family, text_w, max_lines=2):
        draw.text((text_x, y), line, font=f_family, fill=0)
        y += _text_h(draw, line, f_family) + max(1, gap // 2)

    y += gap
    draw.line([(text_x, y), (w_px - margin, y)], fill=0, width=1)
    y += gap

    draw.text((text_x, y), f"ID: SP-{sid}", font=f_id, fill=0)

    buf = io.BytesIO()
    img.convert("1").save(buf, format="PNG")
    return buf.getvalue()
