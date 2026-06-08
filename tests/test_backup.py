"""Testes do backup: rotação diária, cópia externa + alerta, manual e restauração."""
from datetime import datetime
from pathlib import Path

from conftest import ADMIN_USER, ADMIN_PASS


def _make_data(db):
    """Cria um pouco de dado para o backup/restauração ter o que carregar."""
    fid = db.create_filament("MarcaBkp", "PLA", "Basic", "#00ff00")
    db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200,
                    nominal_weight_g=1000, location="B2", purchase_date="",
                    purchase_price=None, notes="")
    return fid


# ── Geração do artefato ──────────────────────────────────────────────────────

def test_make_backup_file_is_valid_and_restorable(app_module, db, tmp_path):
    import backup
    _make_data(db)
    dest = tmp_path / "out.zip"
    backup.make_backup_file(dest)
    assert dest.exists() and dest.stat().st_size > 0
    ok, n_logos, err = backup.restore_from_zip_bytes(dest.read_bytes())
    assert ok is True and err == ""


# ── Rotação diária ───────────────────────────────────────────────────────────

def test_scheduled_backup_uses_weekday_number(app_module, db):
    import backup
    _make_data(db)
    result = backup.run_scheduled_backup()
    slot = datetime.now().isoweekday()
    expected = backup.BACKUPS_DIR / f"spool-backup-{slot}.zip"
    assert result == expected
    assert expected.exists()
    assert db.get_setting("backup_last_result") == "ok"
    # Nome é numérico (independente de idioma), 1..7.
    assert expected.name == f"spool-backup-{slot}.zip"


def test_list_local_backups_reports_real_date(app_module, db):
    import backup
    _make_data(db)
    backup.run_scheduled_backup()
    rows = backup.list_local_backups()
    assert len(rows) == 7
    slot = datetime.now().isoweekday()
    row = next(r for r in rows if r["slot"] == slot)
    assert row["exists"] is True
    assert row["mtime"]            # data real preenchida
    assert row["size_kb"] >= 0


# ── Cópia externa + alerta ───────────────────────────────────────────────────

def test_external_copy_success(app_module, db, tmp_path):
    import backup
    _make_data(db)
    ext = tmp_path / "ext"
    db.set_setting("backup_external_dir", str(ext))
    backup.run_scheduled_backup()
    slot = datetime.now().isoweekday()
    assert (ext / f"spool-backup-{slot}.zip").exists()
    assert db.get_setting("backup_external_error", "") == ""


def test_external_copy_failure_sets_alert_but_keeps_local(app_module, db, tmp_path):
    import backup
    _make_data(db)
    # Aponta a pasta externa para DENTRO de um arquivo → mkdir falha nos dois OSes.
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    db.set_setting("backup_external_dir", str(blocker / "sub"))
    backup.run_scheduled_backup()
    slot = datetime.now().isoweekday()
    # Local OK mesmo com a externa falhando.
    assert (backup.BACKUPS_DIR / f"spool-backup-{slot}.zip").exists()
    assert db.get_setting("backup_last_result") == "ok"
    assert db.get_setting("backup_external_error", "") != ""


def test_test_external_writable(app_module, tmp_path):
    import backup
    assert backup.test_external_writable(str(tmp_path / "newdir")) == ""
    blocker = tmp_path / "f"
    blocker.write_text("x", encoding="utf-8")
    assert backup.test_external_writable(str(blocker / "sub")) != ""


# ── Backup manual (download) mantém o nome com timestamp ─────────────────────

def test_manual_download_keeps_timestamped_name(auth_client):
    resp = auth_client.get("/admin/backup/download")
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    cd = resp.headers.get("Content-Disposition", "")
    # Nome no padrão spool-backup-AAAAMMDD-HHMMSS.zip (não numerado por dia).
    assert "spool-backup-" in cd and ".zip" in cd
    assert "spool-backup-1.zip" not in cd


# ── Restauração a partir de um backup local (item 8) ─────────────────────────

def test_restore_local_roundtrip(auth_client, db):
    import backup
    _make_data(db)
    backup.run_scheduled_backup()
    slot = datetime.now().isoweekday()
    # Apaga o filamento e restaura o backup local — deve voltar.
    fid = db.list_filaments()[0]["id"]
    sid = db.list_spools(active_only=False)[0]["id"]
    db.deactivate_spool(sid)
    resp = auth_client.post("/admin/backup/restore-local", data={"slot": str(slot)})
    assert resp.status_code == 302
    # Dado restaurado (spool ativo de novo).
    assert any(s["active"] == 1 for s in db.list_spools(active_only=False))


def test_restore_local_missing_slot(auth_client):
    resp = auth_client.post("/admin/backup/restore-local", data={"slot": "9"})
    assert resp.status_code == 302   # rejeita slot inválido com flash


# ── Página de backup renderiza com a tabela ──────────────────────────────────

def test_backup_page_renders(auth_client):
    assert auth_client.get("/admin/backup").status_code == 200


def test_backup_config_saves_external_dir(auth_client, db, tmp_path):
    """A pasta externa é configurada na aba Backup (não nas Configurações)."""
    ext = str(tmp_path / "ext")
    resp = auth_client.post("/admin/backup/config", data={"backup_external_dir": ext})
    assert resp.status_code == 302
    assert "/admin/backup" in resp.headers["Location"]
    assert db.get_setting("backup_external_dir") == ext
