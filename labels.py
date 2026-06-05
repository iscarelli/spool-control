import io
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from PIL import Image, ImageDraw, ImageFont
import logger as log_cfg

_log = log_cfg.get_logger("spool.labels")


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


def _spool_code(spool: dict) -> str:
    return f"SP-{str(spool['id']).zfill(4)}"


# ── Layout (PDF vetorial) ─────────────────────────────────────────────────────
# Topo: logo + nome da marca (esq.) | código do rolo (dir.). Separador horizontal
# grosso. Abaixo, à esquerda: Material (grande) / Família / Cor; "Local: <…>" no
# rodapé. Linha vertical fina e o QR à direita ocupando a altura disponível.

def _fit_pdf(c, text: str, font: str, size: float, max_w: float) -> str:
    """Trunca `text` com reticências para caber em `max_w` pontos."""
    text = text or ""
    if c.stringWidth(text, font, size) <= max_w:
        return text
    while text and c.stringWidth(text + "…", font, size) > max_w:
        text = text[:-1]
    return (text + "…") if text else ""


def _draw_label(c, spool: dict, base_url: str, page_w: float, page_h: float):
    """Desenha uma etiqueta na página atual. Coordenadas em pontos (origem inf-esq)."""
    margin = 3 * mm
    scale = page_h / (40 * mm)
    gap = 1.5 * mm * scale

    f_brand = max(6.0, 8.0 * scale)
    f_code = max(6.0, 8.0 * scale)
    f_material = max(10.0, 17.0 * scale)
    f_family = max(5.0, 7.5 * scale)
    f_color = max(8.0, 12.0 * scale)
    f_loc = max(5.0, 7.5 * scale)
    f_cap = max(4.5, 6.0 * scale)

    brand = str(spool.get("brand", ""))
    material = str(spool.get("material", ""))
    family = str(spool.get("family", ""))
    color_nm = str(spool.get("color_name", ""))
    color_hex = str(spool.get("color_hex", "") or "")
    code = _spool_code(spool)
    logo_file = spool.get("logo_file")

    left, right = margin, page_w - margin

    # ── Banda superior: logo + marca (esq.), código (dir.) ──
    logo_h = f_brand * 1.5
    band_top = page_h - margin
    baseline = band_top - logo_h + (logo_h - f_brand) / 2 + f_brand * 0.25

    c.setFont("Helvetica-Bold", f_code)
    code_w = c.stringWidth(code, "Helvetica-Bold", f_code)
    c.drawRightString(right, baseline, code)

    brand_x = left
    if logo_file:
        try:
            limg = Image.open(logo_file).convert("RGBA")
            logo_w = min(logo_h * (limg.width / max(1, limg.height)), page_w * 0.25)
            c.drawImage(ImageReader(limg), left, band_top - logo_h,
                        logo_w, logo_h, mask="auto")
            brand_x = left + logo_w + gap
        except Exception:
            _log.warning("label_pdf.logo_render_failed", logo=str(logo_file),
                         exc_info=True)
            brand_x = left

    brand_max = (right - code_w - gap) - brand_x
    c.setFont("Helvetica-Bold", f_brand)
    c.drawString(brand_x, baseline,
                 _fit_pdf(c, brand, "Helvetica-Bold", f_brand, brand_max))

    # ── Separador grosso ──
    y_sep = band_top - logo_h - gap
    c.setLineWidth(max(1.0, 1.4 * scale))
    c.line(left, y_sep, right, y_sep)

    # ── Área inferior: texto (esq.) | linha vertical fina | QR (dir.) ──
    content_h = y_sep - margin
    qr = min(content_h, page_w * 0.42)
    qr_x = right - qr
    qr_y = margin + (content_h - qr) / 2.0
    url = f"{base_url.rstrip('/')}/spools/{spool['id']}"
    c.drawImage(ImageReader(_make_qr_image(url)), qr_x, qr_y, qr, qr)

    x_v = qr_x - gap
    c.setLineWidth(max(0.3, 0.4 * scale))
    c.line(x_v, margin, x_v, y_sep)

    text_w = (x_v - gap) - left
    location = str(spool.get("location", "") or "")
    g_mat_fam = 6.5 * scale   # respiro Material -> Família
    g_fam_cor = 5.0 * scale   # respiro Família  -> Cor

    cy = y_sep - gap

    # Material (grande, bold)
    c.setFont("Helvetica-Bold", f_material)
    cy -= f_material
    c.drawString(left, cy, _fit_pdf(c, material, "Helvetica-Bold", f_material, text_w))

    # Família (menor)
    if family:
        c.setFont("Helvetica", f_family)
        cy -= f_family + g_mat_fam
        c.drawString(left, cy, _fit_pdf(c, family, "Helvetica", f_family, text_w))

    # Cor (média)
    if color_nm:
        c.setFont("Helvetica-Bold", f_color)
        cy -= f_color + g_fam_cor
        c.drawString(left, cy, _fit_pdf(c, color_nm, "Helvetica-Bold", f_color, text_w))

    # Localização: "Local:" + valor ancorados no rodapé (se cadastrada)
    if location:
        c.setFont("Helvetica", f_loc)
        c.drawString(left, margin, _fit_pdf(c, location, "Helvetica", f_loc, text_w))
        c.setFont("Helvetica", f_cap)
        c.drawString(left, margin + f_loc + 1.5 * scale, "Local:")


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
# Mesma hierarquia do PDF, rasterizada em preto/branco puro no tamanho nativo da
# etiqueta. O navegador faz o threshold e envia via Web Bluetooth (static/niimbot.js).

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


def _fit_png(draw, text: str, font, max_w: int) -> str:
    """Trunca `text` com reticências para caber em `max_w` pixels."""
    text = text or ""
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return (text + "…") if text else ""


def generate_label_png(spool: dict, base_url: str,
                       w_px: int = 584, h_px: int = 354) -> bytes:
    """Etiqueta 1-bit (preto/branco) no tamanho de pixels nativo da Niimbot."""
    img = Image.new("1", (w_px, h_px), 1)  # 1 = branco
    draw = ImageDraw.Draw(img)

    margin = max(4, round(h_px * 0.06))
    left, right = margin, w_px - margin

    f_brand = _load_font(max(12, round(h_px * 0.075)), bold=True)
    f_code = _load_font(max(12, round(h_px * 0.075)), bold=True)
    f_material = _load_font(max(16, round(h_px * 0.15)), bold=True)
    f_family = _load_font(max(10, round(h_px * 0.07)))
    f_color = _load_font(max(12, round(h_px * 0.105)), bold=True)
    f_loc = _load_font(max(9, round(h_px * 0.065)))
    f_cap = _load_font(max(8, round(h_px * 0.05)))

    brand = str(spool.get("brand", ""))
    material = str(spool.get("material", ""))
    family = str(spool.get("family", ""))
    color_nm = str(spool.get("color_name", ""))
    color_hex = str(spool.get("color_hex", "") or "")
    code = _spool_code(spool)
    logo_file = spool.get("logo_file")

    # ── Banda superior: logo + marca (esq.), código (dir.) ──
    band_h = round(h_px * 0.16)
    y = margin
    code_w = draw.textlength(code, font=f_code)
    code_h = _text_h(draw, code, f_code)
    draw.text((right - code_w, y + (band_h - code_h) // 2), code, font=f_code, fill=0)

    bx = left
    if logo_file:
        try:
            limg = Image.open(logo_file)
            # achata transparência sobre branco (favicons têm alpha -> viraria bloco preto)
            if limg.mode in ("RGBA", "LA", "P"):
                limg = limg.convert("RGBA")
                bg = Image.new("RGBA", limg.size, (255, 255, 255, 255))
                limg = Image.alpha_composite(bg, limg).convert("L")
            else:
                limg = limg.convert("L")
            lw = min(round(band_h * (limg.width / max(1, limg.height))),
                     round(w_px * 0.25))
            limg = limg.resize((max(1, lw), band_h)).convert("1")  # dithering
            img.paste(limg, (left, y))
            bx = left + lw + max(4, round(w_px * 0.01))
        except Exception:
            _log.warning("label_png.logo_render_failed", logo=str(logo_file),
                         exc_info=True)
            bx = left

    brand_max = (right - code_w - max(6, round(w_px * 0.02))) - bx
    brand_t = _fit_png(draw, brand, f_brand, brand_max)
    brand_h = _text_h(draw, brand_t, f_brand)
    draw.text((bx, y + (band_h - brand_h) // 2), brand_t, font=f_brand, fill=0)

    # ── Separador grosso ──
    y_sep = margin + band_h + max(2, round(h_px * 0.02))
    lw_sep = max(3, round(h_px * 0.022))
    draw.line([(left, y_sep), (right, y_sep)], fill=0, width=lw_sep)

    # ── Área inferior: texto (esq.) | linha vertical fina | QR (dir.) ──
    top = y_sep + lw_sep + max(3, round(h_px * 0.02))
    avail_h = (h_px - margin) - top
    qr = min(avail_h, round(w_px * 0.42))
    qr_x = right - qr
    qr_y = top + max(0, (avail_h - qr) // 2)
    url = f"{base_url.rstrip('/')}/spools/{spool['id']}"
    qimg = _make_qr_image(url).convert("1").resize((qr, qr), Image.NEAREST)
    img.paste(qimg, (qr_x, qr_y))

    gap = max(4, round(w_px * 0.015))
    x_v = qr_x - gap
    draw.line([(x_v, top), (x_v, h_px - margin)], fill=0,
              width=max(2, round(w_px * 0.004)))

    tx = left
    tw = (x_v - gap) - left
    cy = top
    location = str(spool.get("location", "") or "")
    g_mat_fam = round(h_px * 0.06)   # respiro Material -> Família
    g_fam_cor = round(h_px * 0.045)  # respiro Família  -> Cor

    # Material (grande)
    mat = _fit_png(draw, material, f_material, tw)
    draw.text((tx, cy), mat, font=f_material, fill=0)
    cy += _text_h(draw, mat, f_material)

    # Família (menor)
    if family:
        cy += g_mat_fam
        fam = _fit_png(draw, family, f_family, tw)
        draw.text((tx, cy), fam, font=f_family, fill=0)
        cy += _text_h(draw, fam, f_family)

    # Cor (média)
    if color_nm:
        cy += g_fam_cor
        cnm = _fit_png(draw, color_nm, f_color, tw)
        draw.text((tx, cy), cnm, font=f_color, fill=0)

    # Localização: "Local:" + valor ancorados no rodapé (se cadastrada)
    if location:
        loc = _fit_png(draw, location, f_loc, tw)
        loc_h = _text_h(draw, loc, f_loc)
        cap_h = _text_h(draw, "Local:", f_cap)
        ly = (h_px - margin) - loc_h
        draw.text((tx, ly), loc, font=f_loc, fill=0)
        draw.text((tx, ly - cap_h - max(2, round(h_px * 0.01))), "Local:",
                  font=f_cap, fill=0)

    buf = io.BytesIO()
    img.convert("1").save(buf, format="PNG")
    return buf.getvalue()
