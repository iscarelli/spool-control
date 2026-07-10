"""v1.38.2 — sanitização de color_hex na saída (anti CSS injection).

`color_hex` é campo de texto livre no cadastro de filamento e era injetado em
`style=`/SVG. O filtro `hexcolor` só deixa passar #RGB/#RRGGBB válido.
"""
_PAYLOAD = "#f00;background:url(https://evil.example/x)"


def test_hexcolor_filter_unit(app_module):
    f = app_module.hexcolor
    assert f("#fff") == "#fff"
    assert f("#AabBcc") == "#AabBcc"
    assert f("") == ""
    assert f(_PAYLOAD) == ""                        # payload rejeitado
    assert f(_PAYLOAD, "#e0e0e0") == "#e0e0e0"      # cai no default
    assert f("red") == ""                            # nome de cor não passa
    assert f("#1234") == ""                          # 4 dígitos inválido


def test_malicious_color_not_rendered_in_lists(auth_client, db):
    fid = db.create_filament(brand="Acme", material="PLA", family="PLA",
                             color_hex=_PAYLOAD, color_name="X")
    db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
                    nominal_weight_g=1000.0, location="", purchase_date="",
                    purchase_price=None, notes="")
    for path in ("/spools", "/filaments"):
        html = auth_client.get(path).get_data(as_text=True)
        assert "url(https://evil" not in html, path       # injeção neutralizada
        assert "background:#e0e0e0" in html, path          # amostra usa o neutro
