"""Fixtures de teste.

Cada teste roda contra um banco SQLite TEMPORÁRIO (via SPOOL_DB_PATH), isolado e
descartável — nunca toca no banco real (data/spool.db). O app é reimportado por teste
para que o bootstrap (cria tabelas + usuário admin) rode contra esse banco limpo.
"""
import os
import sys
import pytest

ADMIN_USER = "admin"
ADMIN_PASS = "admin-test-pass"   # >= MIN_PASSWORD_LEN (8)


@pytest.fixture()
def app_module(tmp_path):
    db_file = tmp_path / "test.db"
    os.environ["SPOOL_DB_PATH"] = str(db_file)
    os.environ["SECRET_KEY"] = "test-secret-key"
    os.environ["ADMIN_DEFAULT_PASS"] = ADMIN_PASS
    # Reimporta app + database + routes para que o caminho do banco (lido no import) e
    # o bootstrap valham contra o arquivo temporário deste teste. Os módulos routes.*
    # também precisam ser descartados: senão ficam registrados no objeto `app` antigo
    # (efeito colateral do @app.route) e o novo `app` sobe sem rotas.
    for name in [m for m in sys.modules
                 if m in ("app", "database", "backup", "routes") or m.startswith("routes.")]:
        sys.modules.pop(name, None)
    import app as app_module
    # CSRF desligado nos testes: simplifica os POST (a proteção em si é coberta em prod).
    app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    # O bootstrap cria o admin com troca de senha obrigatória (senha inicial). Para os
    # testes gerais, neutralizamos o flag para usar o admin direto; o fluxo de troca
    # forçada é coberto explicitamente em test_security.py.
    import database
    admin = database.get_user_by_username(ADMIN_USER)
    database.set_must_change_password(admin["id"], False)
    return app_module


@pytest.fixture()
def db(app_module):
    """Módulo database já apontado para o banco temporário do teste."""
    import database
    return database


@pytest.fixture()
def client(app_module):
    return app_module.app.test_client()


@pytest.fixture()
def auth_client(client):
    """Cliente já logado como admin."""
    client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    return client
