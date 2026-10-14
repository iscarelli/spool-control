"""Long color names wrap to 2 lines / shrink instead of being cut with an ellipsis."""
import io

import pypdf
import pytest
from PIL import Image, ImageDraw

import labels
import niimbot_registry


def W(t, sz):  # fake monospace metric
    return len(t) * sz * 0.5


def H(sz, n):
    return sz * (1 + 1.15 * (n - 1))


SIZES = [12, 11, 10, 9, 8, 7]


def fit(text, max_w, max_h=100, sizes=SIZES):
    return labels._fit_lines(text, W, sizes, max_w, max_h, H)


def test_short_name_one_line_full_size():
    assert fit("Red", 100) == (12, ["Red"])


def test_two_words_wrap_at_full_size():
    size, lines = fit("Mangosteen Purple", 100)   # 17 chars * 6 = 102 > 100
    assert size == 12 and lines == ["Mangosteen", "Purple"]


def test_single_long_word_shrinks_instead_of_truncating():
    size, lines = fit("Transparent", 60)           # 11 * 6 = 66 > 60; 10 fits (55)
    assert size == 10 and lines == ["Transparent"]


def test_absurdly_long_falls_back_to_ellipsis_at_floor():
    size, lines = fit("Supercalifragilisticexpialidocious Pigment", 60)
    assert size == 7 and lines[-1].endswith("…")
    assert all(W(line, size) <= 60 for line in lines)


def test_respects_max_h():
    # 2 lines at size 12 need 25.8 > 20: must not wrap at that size
    size, lines = fit("Mangosteen Purple", 100, max_h=20)
    assert H(size, len(lines)) <= 20


def test_empty():
    assert fit("", 50)[1] == [""]


SPOOL = dict(id=7, brand="Soleyin", material="PETG", family="Basic",
             color_hex="#6b3fa0", logo_file=None, translucent=False,
             translucent_marker="")
NAMES = ["Mangosteen Purple", "Transparent", "Matte Strawberry Milk Pink"]
NO_ELLIPSIS = ("Mangosteen Purple", "Transparent")


def _sizes():
    sizes = sorted({(v["w_px"], v["h_px"]) for v in niimbot_registry.LABEL_SIZES.values()})
    assert (384, 240) in sizes and (567, 354) in sizes and (584, 354) in sizes
    return sizes


@pytest.mark.parametrize("loc", ["", "Prateleira 2"])
@pytest.mark.parametrize("name", NAMES)
def test_png_all_sizes_render(monkeypatch, name, loc):
    seen = []
    orig = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        seen.append(text)
        return orig(self, xy, text, *a, **k)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy)
    for w, h in _sizes():
        seen.clear()
        png = labels.generate_label_png(dict(SPOOL, color_name=name, location=loc),
                                        "http://x", w, h)
        assert Image.open(io.BytesIO(png)).size == (w, h)
        if name in NO_ELLIPSIS:
            assert not any("…" in t for t in seen), (name, w, h, seen)


@pytest.mark.parametrize("loc", ["", "Prateleira 2"])
@pytest.mark.parametrize("name", NAMES)
def test_pdf_renders_without_ellipsis(name, loc):
    pdf = labels.generate_label_pdf(dict(SPOOL, color_name=name, location=loc),
                                    "http://x")
    text = pypdf.PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    if name in NO_ELLIPSIS:
        assert "…" not in text
