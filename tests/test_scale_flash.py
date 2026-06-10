"""Testes da página de gravação do firmware da balança (/admin/scale).

Cobre o gate admin, a entrega dos pedaços do firmware + manifesto (offsets), e a
presença do adaptador esp-flash.js + i18n no HTML. O flash em si é Web Serial no
navegador (não testável em pytest). O firmware é gravado em pedaços separados, cada
um no seu offset — como o `pio upload` — porque a imagem merged única falha no
esptool-js."""
import json
from pathlib import Path

FW_DIR = Path(__file__).resolve().parent.parent / "static" / "firmware"


def test_scale_page_requires_admin(app_module, viewer_client, auth_client):
    # anônimo → login; viewer → 403; admin → 200. (Cliente anônimo PRÓPRIO: o fixture
    # `client` é compartilhado com `auth_client`, que o logaria como admin.)
    anon = app_module.app.test_client().get("/admin/scale")
    assert anon.status_code == 302 and "/login" in anon.headers["Location"]
    assert viewer_client.get("/admin/scale").status_code == 403
    assert auth_client.get("/admin/scale").status_code == 200


def test_scale_page_has_flasher_and_i18n(auth_client):
    html = auth_client.get("/admin/scale").get_data(as_text=True)
    # botão com a URL do manifesto + módulo esp-flash.js + blob de i18n
    assert 'id="esp-flash-btn"' in html
    assert "firmware/balanca-c3.json" in html
    assert "data-manifest-url" in html
    assert "esp-flash.js" in html
    assert 'id="esp-flash-i18n"' in html


def test_firmware_parts_are_served(auth_client):
    # Os pedaços são estáticos/públicos (sem segredos) — o gravador baixa cada um.
    manifest = json.loads((FW_DIR / "balanca-c3.json").read_text())
    for part in manifest["parts"]:
        resp = auth_client.get("/static/firmware/" + part["file"])
        assert resp.status_code == 200, part["file"]
        assert int(resp.headers.get("Content-Length", "0")) == part["size"]


def test_firmware_manifest_is_valid():
    # Gerado por deploy/build-firmware-bin.sh; o flasher lê os offsets (como o CLI).
    m = json.loads((FW_DIR / "balanca-c3.json").read_text())
    assert m["chip"] == "esp32c3"
    offsets = [p["offset"] for p in m["parts"]]
    assert offsets == ["0x0", "0x8000", "0xe000", "0x10000"]  # mesmos do pio upload
    assert {p["file"] for p in m["parts"]} == {
        "bootloader.bin", "partitions.bin", "boot_app0.bin", "app.bin"}
    assert len(m["app_sha256"]) == 64


def test_scale_page_shows_firmware_version(auth_client):
    sha8 = json.loads((FW_DIR / "balanca-c3.json").read_text())["app_sha256"][:8]
    html = auth_client.get("/admin/scale").get_data(as_text=True)
    assert sha8 in html
