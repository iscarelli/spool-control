"""Regressão: botões de ação não podem ficar dentro do <form> de edição.

HTML5 proíbe <form> aninhado — o parser do navegador DESCARTA a tag interna, e o
<button type="submit"> que estava dentro dela passa a pertencer ao form EXTERNO.
Efeito prático do bug: "Finalizar Spool" (spools/form.html) e "Remover"
(filaments/form.html) salvavam a edição em vez de executar a ação, e o
`data-sc-confirm` de static/spool.js:24 nunca disparava (o form que carregava o
atributo não existia no DOM).

Teste de ROTA não pega isso — a rota sempre funcionou. Por isso aqui se olha o
HTML RENDERIZADO: nenhum <form> pode abrir enquanto outro está aberto, e o botão
tem que se ligar ao form pelo atributo HTML5 `form=`.
"""
from html.parser import HTMLParser


class _FormNesting(HTMLParser):
    """Coleta os <form> do documento e acusa qualquer abertura aninhada."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.nested = []          # atributos dos <form> abertos dentro de outro
        self.forms = []           # atributos de todos os <form>

    def handle_starttag(self, tag, attrs):
        if tag != "form":
            return
        d = dict(attrs)
        self.forms.append(d)
        if self.depth > 0:
            self.nested.append(d)
        self.depth += 1

    def handle_endtag(self, tag):
        if tag == "form" and self.depth > 0:
            self.depth -= 1


def _parse(html):
    p = _FormNesting()
    p.feed(html)
    return p


def _make_filament(db):
    return db.create_filament(brand="Acme", material="PLA", family="Basic",
                              color_hex="#ff0000")


def _make_spool(db, fid):
    return db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
                           nominal_weight_g=1000.0, location="", purchase_date="",
                           purchase_price=None, notes="")


# ── spools/form.html: "Finalizar Spool" ──────────────────────────────────────

def test_spool_edit_has_no_nested_form(auth_client, db):
    sid = _make_spool(db, _make_filament(db))
    html = auth_client.get(f"/spools/{sid}/edit").get_data(as_text=True)
    p = _parse(html)
    assert p.nested == [], f"<form> aninhado na edição de rolo: {p.nested}"


def test_spool_edit_deactivate_button_bound_by_form_attribute(auth_client, db):
    sid = _make_spool(db, _make_filament(db))
    html = auth_client.get(f"/spools/{sid}/edit").get_data(as_text=True)
    action = f"/spools/{sid}/deactivate"
    p = _parse(html)
    forms = [f for f in p.forms if f.get("action") == action]
    assert len(forms) == 1, "form de finalizar ausente na edição do rolo ativo"
    # É ESTE form que não pode estar aninhado (o bug original).
    assert forms[0] not in p.nested
    fid_attr = forms[0].get("id")
    assert fid_attr, "form de finalizar precisa de id p/ o botão referenciá-lo"
    # A confirmação continua no <form> — é onde static/spool.js lê (e.target).
    assert forms[0].get("data-sc-confirm")
    # O botão vive no flex row do form de edição e se liga pelo atributo `form`.
    assert f'form="{fid_attr}"' in html


def test_spool_edit_finalize_button_keeps_right_alignment(auth_client, db):
    # O `ms-auto` morava no <form> removido; tem que ter migrado para o botão,
    # senão o alinhamento à direita quebra.
    sid = _make_spool(db, _make_filament(db))
    html = auth_client.get(f"/spools/{sid}/edit").get_data(as_text=True)
    btn = html[html.index('form="deactivateForm"'):]
    btn = btn[:btn.index(">")]
    assert "ms-auto" in btn


def test_finalized_spool_edit_has_no_deactivate_form(auth_client, db):
    sid = _make_spool(db, _make_filament(db))
    db.deactivate_spool(sid)
    html = auth_client.get(f"/spools/{sid}/edit").get_data(as_text=True)
    assert f"/spools/{sid}/deactivate" not in html


# ── filaments/form.html: "Remover" ───────────────────────────────────────────

def test_filament_edit_has_no_nested_form(auth_client, db):
    fid = _make_filament(db)
    html = auth_client.get(f"/filaments/{fid}/edit").get_data(as_text=True)
    p = _parse(html)
    assert p.nested == [], f"<form> aninhado na edição de filamento: {p.nested}"


def test_filament_edit_delete_button_bound_by_form_attribute(auth_client, db):
    fid = _make_filament(db)
    html = auth_client.get(f"/filaments/{fid}/edit").get_data(as_text=True)
    action = f"/filaments/{fid}/delete"
    p = _parse(html)
    forms = [f for f in p.forms if f.get("action") == action]
    assert len(forms) == 1, "form de remoção ausente na edição do filamento (admin)"
    assert forms[0] not in p.nested
    fid_attr = forms[0].get("id")
    assert fid_attr, "form de remoção precisa de id p/ o botão referenciá-lo"
    assert forms[0].get("data-sc-confirm")
    assert f'form="{fid_attr}"' in html


def test_filament_edit_delete_button_keeps_right_alignment(auth_client, db):
    fid = _make_filament(db)
    html = auth_client.get(f"/filaments/{fid}/edit").get_data(as_text=True)
    btn = html[html.index('form="deleteFilamentForm"'):]
    btn = btn[:btn.index(">")]
    assert "ms-auto" in btn


def test_filament_edit_hides_delete_for_viewer(viewer_client, db):
    fid = _make_filament(db)
    resp = viewer_client.get(f"/filaments/{fid}/edit")
    if resp.status_code == 200:
        assert f"/filaments/{fid}/delete" not in resp.get_data(as_text=True)


# ── A rota em si (o backend sempre esteve certo — aqui fica o contrato) ──────

def test_post_deactivate_clears_active_flag(auth_client, db):
    sid = _make_spool(db, _make_filament(db))
    assert db.get_spool(sid)["active"] == 1
    resp = auth_client.post(f"/spools/{sid}/deactivate")
    assert resp.status_code == 302
    assert db.get_spool(sid)["active"] == 0
