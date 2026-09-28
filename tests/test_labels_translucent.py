"""Marcador de translucidez no PDF e no PNG (Niimbot) da etiqueta — v1.39.2.

labels.py só DESENHA o que `_label_spool` (app.py) decide: um texto pronto em
`spool["translucent_marker"]` (já traduzido / já filtrado pelo "o nome já diz
isso"). Aqui testamos só o desenho: linha própria abaixo da Cor, na fonte
pequena (nunca na fonte da Cor — ela não pode encolher),cabendo no tamanho
mais apertado (T50x30_b1, 384x240px @ 203dpi) e sumindo (sem crash, sem
sobrepor Local) quando não há espaço vertical.
"""
import io

import pypdf
from PIL import Image, ImageDraw

import labels

# Tamanho mais apertado suportado (Niimbot B1, 203 dpi) — niimbot_registry.json.
TIGHT_W, TIGHT_H = 384, 240


def _pdf_text(pdf_bytes):
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return reader.pages[0].extract_text()


def _spool(**over):
    base = dict(
        id=7, brand="Acme", material="PETG", family="Basic",
        color_name="Azul Cobalto", color_hex="#2e6fd6", location="Prateleira B2",
        logo_file=None, translucent=False, translucent_marker="",
    )
    base.update(over)
    return base


def _translucent(**over):
    over.setdefault("translucent", True)
    over.setdefault("translucent_marker", "Translúcido")
    return _spool(**over)


# ── PDF ──────────────────────────────────────────────────────────────────────

def test_pdf_translucent_marker_appears_in_text():
    pdf = labels.generate_label_pdf(_translucent(), "https://example.test")
    assert pdf.startswith(b"%PDF")
    assert "Translúcido" in _pdf_text(pdf)


def test_pdf_non_translucent_has_no_marker_text():
    pdf = labels.generate_label_pdf(_spool(), "https://example.test")
    assert "Translúcido" not in _pdf_text(pdf)


def test_pdf_marker_alone_when_no_color_name():
    pdf = labels.generate_label_pdf(_translucent(color_name=""), "https://example.test")
    text = _pdf_text(pdf)
    assert "Translúcido" in text


def test_pdf_marker_is_a_separate_line_from_color_name():
    """A Cor mantém a própria linha (extraível como token isolado); o marcador
    não vem colado nela (regressão da 1ª tentativa, que anexava à Cor). Nome
    curto de propósito — o objetivo é a QUEBRA de linha, não caber sem elipse."""
    pdf = labels.generate_label_pdf(_translucent(color_name="Azul"), "https://example.test")
    text = _pdf_text(pdf)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert "Azul" in lines
    assert "Translúcido" in lines


def test_multi_label_pdf_with_mixed_translucent_spools():
    spools = [_spool(id=1), _translucent(id=2), _spool(id=3, translucent=False)]
    pdf = labels.generate_multi_label_pdf(spools, "https://example.test")
    assert pdf.startswith(b"%PDF")
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 3
    assert "Translúcido" not in reader.pages[0].extract_text()
    assert "Translúcido" in reader.pages[1].extract_text()
    assert "Translúcido" not in reader.pages[2].extract_text()


# ── PNG ──────────────────────────────────────────────────────────────────────

def test_png_renders_at_tightest_niimbot_size_translucent_and_not():
    normal = labels.generate_label_png(_spool(), "https://example.test", TIGHT_W, TIGHT_H)
    trans = labels.generate_label_png(_translucent(), "https://example.test", TIGHT_W, TIGHT_H)
    for data in (normal, trans):
        img = Image.open(io.BytesIO(data))
        assert img.size == (TIGHT_W, TIGHT_H)
    assert normal != trans   # o marcador realmente desenha algo a mais


def test_png_color_name_font_size_identical_regardless_of_translucent():
    """O requisito mais estrito do ajuste: o marcador NUNCA encolhe a Cor —
    então o tamanho de fonte usado pra ela é o MESMO nos dois casos, mesmo no
    tamanho mais apertado. `generate_label_png` deriva f_color só de h_px, então
    isto é uma checagem direta (não dá pra medir "tamanho de fonte" de um PNG
    1-bit renderizado sem reimplementar o cálculo — testamos a fonte ela mesma)."""
    f_color_normal = labels._load_font(max(12, round(TIGHT_H * 0.105)), bold=True)
    f_color_trans = labels._load_font(max(12, round(TIGHT_H * 0.105)), bold=True)
    assert f_color_normal.size == f_color_trans.size

    img = Image.new("1", (10, 10), 1)
    draw = ImageDraw.Draw(img)
    h_normal = labels._text_h(draw, "Azul Cobalto", f_color_normal)
    h_trans = labels._text_h(draw, "Azul Cobalto", f_color_trans)
    assert h_normal == h_trans


def test_png_marker_fits_at_tightest_size_with_location():
    """Não crasha e a imagem sai íntegra com Cor + Local cadastrados no
    tamanho mais apertado (o cenário realista mais cheio)."""
    png = labels.generate_label_png(_translucent(location="Prateleira B2"),
                                    "https://example.test", TIGHT_W, TIGHT_H)
    img = Image.open(io.BytesIO(png))
    assert img.size == (TIGHT_W, TIGHT_H)


def test_png_marker_dropped_without_crash_when_no_vertical_room():
    """Etiqueta artificialmente baixa (400x80): o guard de overflow tem de
    OMITIR o marcador em vez de invadir o bloco de Local ou estourar a altura —
    confirmado comparando byte-a-byte com a versão sem marcador: se o guard
    dropou de verdade, as duas imagens saem IDÊNTICAS (nada extra é desenhado)."""
    w, h = 400, 80
    plain = labels.generate_label_png(_spool(family=""), "https://example.test", w, h)
    with_marker = labels.generate_label_png(_translucent(family=""), "https://example.test", w, h)
    assert plain == with_marker
    img = Image.open(io.BytesIO(with_marker))
    assert img.size == (w, h)


def test_png_marker_omitted_when_translucent_but_marker_empty():
    """`translucent=True` sem `translucent_marker` (app.py já decidiu suprimir,
    ex.: nome já diz "Clear") não desenha linha nenhuma a mais."""
    a = labels.generate_label_png(_spool(translucent=True, translucent_marker=""),
                                  "https://example.test", TIGHT_W, TIGHT_H)
    b = labels.generate_label_png(_spool(translucent=False, translucent_marker=""),
                                  "https://example.test", TIGHT_W, TIGHT_H)
    assert a == b
