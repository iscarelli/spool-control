"""Stale-page protection: version exposed on the page, /health agrees, banner markup."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_no_inline_handlers import INLINE_HANDLER

VERSION = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()


def test_body_carries_version_matching_file_and_footer(auth_client):
    html = auth_client.get("/").get_data(as_text=True)
    assert f'<body data-app-version="{VERSION}"' in html
    assert f'<div class="sc-version">v{VERSION}</div>' in html


def test_health_version_matches_file(client):
    assert client.get("/health").get_json()["version"] == VERSION


def test_banner_markup_and_script(auth_client):
    html = auth_client.get("/").get_data(as_text=True)
    assert 'id="scUpdateBanner"' in html and "hidden" in html
    assert 'id="scUpdateReload"' in html
    assert "version-check.js" in html
    assert INLINE_HANDLER.search(html) is None
    assert auth_client.get("/static/version-check.js").status_code == 200


def test_banner_strings_translated():
    import translations as i18n
    for k in ("Nova versão disponível", "Recarregar"):
        assert k in i18n._EN and k in i18n._ES


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_decide_pure_function():
    cases = [
        ["1", "1", False, 0, 1000, "nothing"],
        ["1", "2", False, 0, 1000, "reload"],
        ["1", "2", True, 0, 1000, "banner"],
        ["1", "2", False, 900, 1000, "banner"],
        ["1", "2", False, 1000, 302000, "reload"],
        ["1", None, False, 0, 1000, "nothing"],
    ]
    script = ("const v=require('./static/version-check.js');"
              f"console.log(JSON.stringify({json.dumps(cases)}.map(c=>v.decide(...c.slice(0,5)))))")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == [c[5] for c in cases]
