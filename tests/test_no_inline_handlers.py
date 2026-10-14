"""Inline event-handler attributes are silently blocked by the nonce CSP (app.py:315).

A `onclick=` on a button does nothing in production, with no error. Handlers must be
registered from nonce'd scripts or static/spool.js. See docs/ARMADILHAS.md.
"""
import re

INLINE_HANDLER = re.compile(r"<[^>]*\son[a-z]+\s*=", re.IGNORECASE)

REPORTS = [
    "/reports/by-material", "/reports/by-location", "/reports/low-stock",
    "/reports/low-stock-filaments", "/reports/consumption", "/reports/weight-history",
]


def _make_spool(db):
    fid = db.create_filament("MarcaTeste", "PLA", "Basic", "#ff0000")
    sid = db.create_spool(
        filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
        nominal_weight_g=1000.0, location="A1", purchase_date="",
        purchase_price=None, notes="",
    )
    return fid, sid


def test_no_inline_handlers_on_pages(auth_client, db):
    fid, sid = _make_spool(db)
    urls = ["/", "/spools", "/spools?group=1", "/filaments", f"/filaments/{fid}",
            f"/spools/{sid}"] + REPORTS
    for url in urls:
        resp = auth_client.get(url)
        assert resp.status_code == 200, url
        html = resp.get_data(as_text=True)
        m = INLINE_HANDLER.search(html)
        assert m is None, f"{url}: inline handler {m.group(0)[-60:]!r}"


def test_weigh_button_present_for_writer(auth_client, db):
    _make_spool(db)
    html = auth_client.get("/spools").get_data(as_text=True)
    assert re.search(r"<button[^>]*weigh-btn", html)
    assert "weighModal" in html


def test_report_print_buttons_use_data_attribute(auth_client, db):
    _make_spool(db)
    for url in REPORTS:
        assert "data-sc-print" in auth_client.get(url).get_data(as_text=True), url
