"""Cache-busting de assets estáticos (`?v=<hash-do-conteúdo>`) + Cache-Control.

O bug que isto previne é silencioso: depois de uma atualização o navegador serve o
`spool.js`/`spool.css` que já tinha em cache, a mudança recém-publicada não aparece
e nada falha visivelmente. As duas metades do fix são testadas aqui — o carimbo na
URL do asset E o `no-cache` no HTML que carrega essa URL.
"""
import os
import re
import hashlib

import pytest
from flask import url_for


def _static_url(app_module, filename):
    """URL que o template geraria para `filename` (com o carimbo, se houver)."""
    with app_module.app.test_request_context():
        return url_for("static", filename=filename)


def _stamp(url):
    """Valor do `?v=` numa URL de asset, ou None se a URL saiu sem carimbo."""
    m = re.search(r"[?&]v=([0-9a-f]+)", url)
    return m.group(1) if m else None


@pytest.fixture()
def temp_asset(app_module):
    """Arquivo descartável dentro do `static_folder`, removido no teardown."""
    path = os.path.join(app_module.app.static_folder, "_test-cache-bust.tmp.css")
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


# ── HTML: revalida sempre (a outra metade do fix) ────────────────────────────

def test_html_page_is_no_cache(auth_client):
    resp = auth_client.get("/")
    assert resp.status_code == 200
    assert "no-cache" in resp.headers.get("Cache-Control", "")


def test_html_carries_stamped_assets(auth_client):
    html = auth_client.get("/").get_data(as_text=True)
    # Regex, não string exata: o hash muda a cada edição do arquivo.
    assert re.search(r"spool\.css\?v=[0-9a-f]{8}", html)
    assert re.search(r"spool\.js\?v=[0-9a-f]{8}", html)


# ── Assets: imutáveis quando carimbados ──────────────────────────────────────

def test_stamped_asset_is_immutable(client, app_module):
    url = _static_url(app_module, "spool.css")
    assert _stamp(url), "spool.css saiu sem ?v="
    cc = client.get(url).headers.get("Cache-Control", "")
    assert "max-age=31536000" in cc
    assert "immutable" in cc


def test_unstamped_asset_is_not_immutable(client):
    cc = client.get("/static/spool.css").headers.get("Cache-Control", "")
    assert "immutable" not in cc


# ── O carimbo é o CONTEÚDO, não o mtime ──────────────────────────────────────

def test_stamp_follows_content_not_mtime(app_module, temp_asset):
    """Conteúdo diferente → carimbo diferente, mesmo com o MESMO tamanho.

    Os mtimes são fixados com `os.utime` para não depender da resolução do relógio:
    o tamanho é idêntico nas duas escritas, então quem invalidou o cache foi o
    mtime — e o valor devolvido é, comprovadamente, o hash do conteúdo."""
    name = os.path.basename(temp_asset)

    with open(temp_asset, "wb") as fh:
        fh.write(b"AAAA")
    os.utime(temp_asset, (1000, 1000))
    first = _stamp(_static_url(app_module, name))
    assert first == hashlib.sha256(b"AAAA").hexdigest()[:8]

    with open(temp_asset, "wb") as fh:
        fh.write(b"BBBB")          # mesmo tamanho, conteúdo outro
    os.utime(temp_asset, (2000, 2000))
    second = _stamp(_static_url(app_module, name))
    assert second == hashlib.sha256(b"BBBB").hexdigest()[:8]
    assert first != second


def test_stamp_survives_mtime_only_change(app_module, temp_asset):
    """Mesmo conteúdo com mtime novo → MESMO carimbo.

    É o cenário do deploy: `git archive | tar` reescreve a árvore inteira, então o
    mtime de todo arquivo muda a cada release. Um carimbo derivado do mtime
    invalidaria o cache do navegador inteiro à toa; o do conteúdo, não."""
    name = os.path.basename(temp_asset)

    with open(temp_asset, "wb") as fh:
        fh.write(b"same content")
    os.utime(temp_asset, (1000, 1000))
    before = _stamp(_static_url(app_module, name))

    os.utime(temp_asset, (3000, 3000))   # só o mtime muda
    assert _stamp(_static_url(app_module, name)) == before


# ── Fail-safe e regressões ───────────────────────────────────────────────────

def test_missing_asset_does_not_raise_and_has_no_stamp(app_module):
    # Um logo faltando em static/brands/ não pode derrubar a página.
    url = _static_url(app_module, "nao-existe.css")
    assert _stamp(url) is None
    assert app_module._static_version("nao-existe.css") is None


def test_path_escaping_static_folder_has_no_stamp(app_module):
    assert app_module._static_version("../app.py") is None


def test_no_store_endpoint_stays_no_store(auth_client):
    # Regressão: o Cache-Control definido de propósito por uma rota vence o default.
    resp = auth_client.get("/admin/integrations/homeassistant/key")
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
