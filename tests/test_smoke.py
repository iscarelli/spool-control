"""Testes de fumaça ("smoke tests") — cobrem o COMPORTAMENTO dos fluxos principais
(login, cadastro, pesagem, permissão de admin), não os detalhes de implementação.
Servem de rede de segurança: se uma edição futura quebrar um destes, o pytest acusa
antes da release.
"""
from conftest import ADMIN_USER, ADMIN_PASS


# ── Health ───────────────────────────────────────────────────────────────────

def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


# ── Autenticação ─────────────────────────────────────────────────────────────

def test_dashboard_requires_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_wrong_password_is_rejected(client, db):
    resp = client.post("/login", data={"username": ADMIN_USER, "password": "errada"})
    assert resp.status_code == 200          # re-renderiza o login, não loga
    # A tentativa falha foi registrada (insumo do rate-limit anti força-bruta).
    assert db.count_recent_login_failures("127.0.0.1", 15) >= 1
    # E continua sem acesso ao painel.
    assert client.get("/").status_code == 302


def test_login_correct_password_grants_access(auth_client):
    assert auth_client.get("/").status_code == 200


# ── Cadastro de filamento ────────────────────────────────────────────────────

def test_create_filament_appears_in_list(auth_client):
    auth_client.post("/filaments/new", data={
        "brand": "MarcaTeste", "material": "PLA", "family": "Basic",
        "color_hex": "#ff0000", "diameter_mm": "1.75", "notes": "",
    })
    resp = auth_client.get("/filaments")
    assert resp.status_code == 200
    assert b"MarcaTeste" in resp.data


# ── Fluxo de pesagem ─────────────────────────────────────────────────────────

def _make_spool(db, tare=200.0, nominal=1000.0):
    fid = db.create_filament("MarcaTeste", "PLA", "Basic", "#ff0000")
    return db.create_spool(
        filament_id=fid, spool_model_id=None, custom_tare_g=tare,
        nominal_weight_g=nominal, location="A1", purchase_date="",
        purchase_price=None, notes="",
    )


def test_weigh_records_net_weight(auth_client, db):
    sid = _make_spool(db, tare=200, nominal=1000)
    auth_client.post(f"/spools/{sid}/weigh", data={"gross_weight_g": "1200", "notes": ""})
    readings = db.list_weight_readings(spool_id=sid)
    assert len(readings) == 1
    assert readings[0]["net_weight_g"] == 1000   # 1200 bruto − 200 tara


def test_weigh_below_tare_is_rejected(auth_client, db):
    sid = _make_spool(db, tare=200, nominal=1000)
    # Bruto (100) menor que a tara (200) — deve ser recusado, sem gravar leitura.
    auth_client.post(f"/spools/{sid}/weigh", data={"gross_weight_g": "100", "notes": ""})
    assert db.list_weight_readings(spool_id=sid) == []


# ── Permissão de admin ───────────────────────────────────────────────────────

def test_admin_route_blocks_anonymous(client):
    resp = client.get("/admin/users")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_admin_route_forbids_non_admin(client, db):
    from werkzeug.security import generate_password_hash
    # must_change=False isola o teste de AUTORIZAÇÃO do gate de troca de senha
    # (que, se ativo, redirecionaria antes do 403).
    db.create_user("comum", generate_password_hash("senha-viewer"), role="viewer",
                   must_change=False)
    client.post("/login", data={"username": "comum", "password": "senha-viewer"})
    assert client.get("/admin/users").status_code == 403


# ── Política de senha mínima ─────────────────────────────────────────────────

def test_new_user_rejects_short_password(auth_client, db):
    auth_client.post("/admin/users/new", data={
        "username": "curto", "password": "1234567", "role": "viewer",  # 7 < 8
    })
    assert db.get_user_by_username("curto") is None


def test_new_user_accepts_valid_password(auth_client, db):
    auth_client.post("/admin/users/new", data={
        "username": "valido", "password": "12345678", "role": "viewer",  # 8 ok
    })
    assert db.get_user_by_username("valido") is not None


# ── Renderização das páginas (pega url_for/endpoint quebrado nos templates) ───

# Páginas sem parâmetro de URL. /admin/update fica de fora (consulta a API do
# GitHub na renderização — não queremos rede nos testes).
SIMPLE_PAGES = [
    "/", "/filaments", "/filaments/new", "/spool-models", "/spool-models/new",
    "/spools", "/spools/new", "/weigh", "/search", "/label-queue",
    "/reports/stats", "/reports/inventory", "/reports/by-material",
    "/reports/by-location", "/reports/low-stock", "/reports/weight-history",
    "/admin/users", "/admin/brands", "/admin/settings", "/admin/backup",
]


def test_simple_pages_render(auth_client):
    for url in SIMPLE_PAGES:
        resp = auth_client.get(url)
        assert resp.status_code == 200, f"{url} retornou {resp.status_code}"


def test_spool_detail_pages_render(auth_client, db):
    """Páginas que dependem de um spool existente (detalhe, edição, pesagem,
    etiquetas) — cobrem os templates que usam url_for de várias rotas."""
    sid = _make_spool(db)
    fid = db.get_spool(sid)["filament_id"]
    for url in (f"/spools/{sid}", f"/spools/{sid}/edit", f"/spools/{sid}/weigh",
                f"/filaments/{fid}", f"/filaments/{fid}/edit",
                f"/spools/{sid}/label.pdf", f"/spools/{sid}/qr.png"):
        resp = auth_client.get(url)
        assert resp.status_code == 200, f"{url} retornou {resp.status_code}"


def test_unweighed_spool_detail_shows_nominal(auth_client, db):
    """Rolo não pesado: o detalhe assume o peso nominal (cheio) em vez de exibir 0/—.
    Trava a correção visual — consistente com relatórios e donuts."""
    sid = _make_spool(db, nominal=1000)
    html = auth_client.get(f"/spools/{sid}").get_data(as_text=True)
    assert "1000g" in html
    assert "Não pesado ainda" not in html


# ── Autoatualização: o app só escreve o flag (sem privilégio) ────────────────

def test_update_run_writes_flag(auth_client, db):
    """POST /admin/update/run deve criar o flag que o vigia root (systemd .path)
    consome — o app não executa nada privilegiado."""
    flag = db.DB_PATH.parent / ".update-requested"
    if flag.exists():
        flag.unlink()
    resp = auth_client.post("/admin/update/run",
                            headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert flag.exists()


# ── Catálogo de filamentos (SpoolmanDB vendorado) ────────────────────────────

def test_filament_catalog_loaded():
    """O snapshot vendorado carrega e tem conteúdo."""
    import filament_catalog as catalog
    assert catalog.available() is True
    assert catalog.BRANDS and catalog.MATERIALS and catalog.FILAMENTS
    e = catalog.FILAMENTS[0]
    assert {"brand", "material", "color_hex", "diameter"} <= set(e)


def test_filament_catalog_api(auth_client):
    resp = auth_client.get("/api/filament-catalog")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data["filaments"], list) and data["filaments"]
    assert isinstance(data["brands"], list) and isinstance(data["materials"], list)


def test_filament_catalog_api_requires_login(client):
    resp = client.get("/api/filament-catalog")
    assert resp.status_code in (302, 401)
