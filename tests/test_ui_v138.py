"""Testes de v1.38.0:

  - Prompt de cadastrar rolo após criar filamento.
  - Data de compra pré-preenchida com hoje no cadastro de rolo.
  - Coluna "Cor" na lista de rolos.
  - "Ver novidades" acumulado (CHANGELOG entre a versão instalada e a última).
"""
from datetime import date

from conftest import ADMIN_USER, ADMIN_PASS


_SAMPLE_CHANGELOG = """# Changelog

## [1.37.0] — 2026-07-10
### Added
- recurso do 1.37

## [1.36.0] — 2026-06-10
### Added
- recurso do 1.36

## [1.35.0] — 2026-05-10
### Added
- recurso do 1.35
"""


# ── Item 1: prompt de rolo após criar filamento ──────────────────────────────

def test_filament_create_redirects_with_spool_prompt(auth_client):
    resp = auth_client.post("/filaments/new", data={
        "brand": "Acme", "material": "PLA", "family": "PLA",
        "color_hex": "#123456", "color_name": "Azul", "diameter_mm": "1.75",
    })
    assert resp.status_code == 302
    assert "spool_prompt=1" in resp.headers["Location"]


def test_filament_detail_shows_spool_prompt_modal(auth_client, db):
    auth_client.post("/filaments/new", data={
        "brand": "Acme", "material": "PLA", "family": "PLA", "diameter_mm": "1.75",
    })
    fid = db.list_filaments()[0]["id"]
    html = auth_client.get(f"/filaments/{fid}?spool_prompt=1").get_data(as_text=True)
    assert "spoolPromptModal" in html
    assert f"/spools/new?filament_id={fid}" in html
    # sem o parâmetro, nada de modal
    assert "spoolPromptModal" not in auth_client.get(f"/filaments/{fid}").get_data(as_text=True)


# ── Item 2: data de compra default = hoje ────────────────────────────────────

def test_new_spool_form_prefills_today(auth_client):
    html = auth_client.get("/spools/new").get_data(as_text=True)
    today = date.today().isoformat()   # o único campo de data que assume hoje é a compra
    assert f'value="{today}"' in html


# ── Item 4: coluna Cor na lista ──────────────────────────────────────────────

def test_spool_list_shows_color(auth_client, db):
    fid = db.create_filament(brand="Acme", material="PLA", family="PLA",
                             color_hex="#ff0000", color_name="Vermelho")
    db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
                    nominal_weight_g=1000.0, location="", purchase_date="",
                    purchase_price=None, notes="")
    html = auth_client.get("/spools").get_data(as_text=True)
    assert "Vermelho" in html          # nome informado aparece
    assert "#ff0000" in html           # amostra da cor


def test_filament_list_shows_color(auth_client, db):
    db.create_filament(brand="Acme", material="PLA", family="PLA",
                       color_hex="#00ff00", color_name="Verde")
    html = auth_client.get("/filaments").get_data(as_text=True)
    assert "Verde" in html and "#00ff00" in html


def test_spool_list_color_falls_back_to_bucket(auth_client, db):
    # sem color_name: usa o balde derivado do hexa (classify_color)
    fid = db.create_filament(brand="Acme", material="PLA", family="PLA",
                             color_hex="#ff0000", color_name="")
    db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
                    nominal_weight_g=1000.0, location="", purchase_date="",
                    purchase_price=None, notes="")
    expected = db.classify_color("#ff0000")
    html = auth_client.get("/spools").get_data(as_text=True)
    assert expected and expected in html


# ── Item 3: "Ver novidades" acumulado ────────────────────────────────────────

def test_slice_changelog_picks_range(app_module):
    md = app_module._slice_changelog(_SAMPLE_CHANGELOG, current="1.35.0", latest="1.37.0")
    assert "recurso do 1.37" in md
    assert "recurso do 1.36" in md
    assert "recurso do 1.35" not in md   # a versão instalada é exclusiva
    # cabeçalhos de versão preservados p/ o card renderizar cada bloco
    assert "[1.37.0]" in md and "[1.36.0]" in md


def test_cumulative_notes_slices_from_changelog(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "current_version", lambda: "1.35.0")
    app_module._release_cache.update(tag="1.37.0", ts=0.0, ok=True)
    app_module._cumulative_cache.update(key=None, notes="")
    monkeypatch.setattr(app_module, "_changelog_md", lambda tag: _SAMPLE_CHANGELOG)
    notes, complete = app_module.cumulative_release_notes()
    assert complete is True
    assert "recurso do 1.37" in notes and "recurso do 1.36" in notes
    assert "recurso do 1.35" not in notes
    # mais de uma seção de versão presente — é o histórico acumulado, não só a última
    assert "[1.37.0]" in notes and "[1.36.0]" in notes


def test_cumulative_notes_fallback_when_no_tag(app_module, monkeypatch):
    app_module._release_cache.update(tag=None, ts=0.0, ok=False)
    monkeypatch.setattr(app_module, "latest_release_notes", lambda: "notas da ultima")
    notes, complete = app_module.cumulative_release_notes()
    assert notes == "notas da ultima"
    assert complete is False


def test_cumulative_notes_fallback_on_fetch_error(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "current_version", lambda: "1.30.0")
    app_module._release_cache.update(tag="1.37.0", ts=0.0, ok=True)
    app_module._cumulative_cache.update(key=None, notes="")
    monkeypatch.setattr(app_module, "_changelog_md",
                        lambda tag: (_ for _ in ()).throw(OSError("sem rede")))
    monkeypatch.setattr(app_module, "latest_release_notes", lambda: "notas da ultima")
    notes, complete = app_module.cumulative_release_notes()
    # fail-open preservado: cai pra nota da última release, mas avisa que é incompleto
    assert notes == "notas da ultima"
    assert complete is False


# ── Aviso "histórico incompleto": só quando vale a pena avisar ───────────────

def test_no_warning_for_single_patch_bump(app_module):
    # 1.38.2 → 1.38.3 é um patch só acima: a nota da última release JÁ é a
    # história inteira, avisar seria ruído mesmo com complete=False.
    assert app_module.notes_incomplete_warning(False, "1.38.2", "1.38.3") is False


def test_warning_for_bigger_gap(app_module):
    assert app_module.notes_incomplete_warning(False, "1.30.0", "1.37.0") is True


def test_no_warning_when_notes_are_complete(app_module):
    assert app_module.notes_incomplete_warning(True, "1.30.0", "1.37.0") is False


# ── /admin/update: o aviso aparece só quando o fallback foi mesmo acionado ────
#
# Nota: `routes/admin.py` importa `current_version` do `app` com `from app import
# current_version` — é um nome próprio no módulo routes.admin, então monkeypatchar
# `app_module.current_version` NÃO o afeta. Por isso estes dois testes usam a versão
# REAL do arquivo VERSION (via `app_module.current_version()`) em vez de fingir uma,
# e fixam um `latest` bem à frente dela (gap grande, nunca um patch único).

def test_update_page_shows_incomplete_warning_on_fallback(app_module, auth_client, monkeypatch):
    monkeypatch.setattr(app_module, "_latest_release_tag_via_web", lambda: "v9.9.9")
    monkeypatch.setattr(app_module, "latest_release_notes", lambda: "notas da ultima")
    # Força o caminho de fallback: a busca do CHANGELOG cru falha.
    monkeypatch.setattr(app_module, "_changelog_md",
                        lambda tag: (_ for _ in ()).throw(OSError("sem rede")))
    html = auth_client.get("/admin/update").get_data(as_text=True)
    assert "histórico completo" in html   # aviso de notas possivelmente incompletas


def test_update_page_hides_warning_when_slicing_works(app_module, auth_client, monkeypatch):
    cur = app_module.current_version()
    changelog = (
        "# Changelog\n\n"
        "## [9.9.9] — 2026-07-28\n### Added\n- recurso novo\n\n"
        f"## [{cur}] — 2026-01-01\n### Added\n- recurso antigo\n"
    )
    monkeypatch.setattr(app_module, "_latest_release_tag_via_web", lambda: "v9.9.9")
    monkeypatch.setattr(app_module, "_changelog_md", lambda tag: changelog)
    html = auth_client.get("/admin/update").get_data(as_text=True)
    assert "recurso novo" in html         # notas acumuladas carregadas de verdade
    assert "histórico completo" not in html
