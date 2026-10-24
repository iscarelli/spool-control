"""Notificações push do próprio usuário: aparelhos inscritos, avisos e teste de permissões.

Código do envio e das chaves VAPID em push.py; doc em docs/notificacoes.md. Toda rota age
sobre as linhas do USUÁRIO LOGADO — nenhuma recebe user_id."""
from flask import flash, jsonify, redirect, render_template, request, session, url_for

import database as db
import logger as log_cfg
import push
from app import app, login_required, demo_blocked, t, DEMO_MODE, WRITE_ROLES

log = log_cfg.get_logger()

GRAMS_MIN, GRAMS_MAX = 1, 5000
DAYS_MIN, DAYS_MAX = 1, 60


def _can_write():
    return session.get("role") in WRITE_ROLES


def _json_guard():
    """Demo mode blocks account actions; for the JSON endpoints that is a 403, not a redirect."""
    if DEMO_MODE:
        return jsonify(error=t("Função desabilitada na versão demonstrativa.")), 403
    return None


def _int_in(raw, lo, hi):
    """int(raw) if it is a whole number in [lo, hi], else None."""
    try:
        n = int(str(raw).strip())
    except ValueError:
        return None
    return n if lo <= n <= hi else None


def _device_label(kind):
    return {"iPhone": "iPhone", "Android": "Android"}.get(kind) or t("computador")


@app.route("/account/notifications")
@login_required
@demo_blocked
def account_notifications():
    uid = session["user_id"]
    devices = [{"id": s["id"], "name": _device_label(push.device_kind(s["user_agent"])),
                "created_at": s["created_at"][:10], "last_ok_at": s["last_ok_at"][:10]}
               for s in db.list_push_subscriptions(uid)]
    # Strings the static JS shows (it does not go through Jinja); the page reads them from data-*.
    js_i18n = {k: t(k) for k in (
        "Permitida", "Ainda não pedida", "Toque em Testar", "Sem informação neste aparelho",
        "Câmera OK", "Este navegador não dá acesso à câmera.", "Este aparelho não tem câmera.",
        "Não consegui abrir a câmera agora.", "Notificações permitidas",
        "Bloqueada. Para liberar:",
        "toque no cadeado ao lado do endereço › Permissões › Permitir",
        "Ajustes › Safari › Câmera › Permitir", "Ajustes › Safari › Notificações › Permitir",
        "Ajustes › Spool › Câmera › Permitir", "Ajustes › Spool › Notificações › Permitir",
        "Este navegador não oferece notificações aqui.",
        "No iPhone elas só funcionam no app instalado na Tela de Início.",
        "Este aparelho está inscrito.", "Este aparelho ainda não está inscrito.",
        "Pedindo permissão…", "A permissão não foi concedida.",
        "Permissão negada.", "Inscrito. Envie o teste para conferir.",
        "O servidor recusou a inscrição.", "Não foi possível inscrever este aparelho.",
        "Notificações desativadas neste aparelho.", "Não foi possível desativar.",
        "Enviando…", "Enviada: o serviço de push aceitou.",
        "Inscrição expirada e apagada: ative de novo.", "O serviço de push recusou.",
        "Não consegui enviar.", "Este aparelho não está inscrito: ative as notificações primeiro.",
        "Sem conexão: o teste não foi enviado.", "Não foi possível enviar o teste.",
    )}
    return render_template(
        "account/notifications.html",
        public_key=push.public_key(),
        devices=devices,
        prefs=db.get_notification_prefs(uid),
        can_write=_can_write(),
        js_i18n=js_i18n,
        grams_max=GRAMS_MAX, days_max=DAYS_MAX,
    )


@app.route("/account/notifications/prefs", methods=["POST"])
@login_required
@demo_blocked
def account_notifications_prefs():
    uid = session["user_id"]
    cur = db.get_notification_prefs(uid)
    grams = _int_in(request.form.get("low_stock_g") or cur["low_stock_g"], GRAMS_MIN, GRAMS_MAX)
    days = _int_in(request.form.get("weigh_reminder_days") or cur["weigh_reminder_days"],
                   DAYS_MIN, DAYS_MAX)
    if grams is None:
        flash(t("Informe um peso entre {lo} e {hi} g.").format(lo=GRAMS_MIN, hi=GRAMS_MAX), "danger")
        return redirect(url_for("account_notifications"))
    if days is None:
        flash(t("Informe um número de dias entre {lo} e {hi}.").format(lo=DAYS_MIN, hi=DAYS_MAX),
              "danger")
        return redirect(url_for("account_notifications"))
    # The weighing reminder is for people who weigh: a read-only user can neither see nor enable it.
    reminder = bool(request.form.get("weigh_reminder_on")) and _can_write()
    db.save_notification_prefs(uid, bool(request.form.get("low_stock_on")), grams,
                               bool(request.form.get("last_spool_on")), reminder, days,
                               bool(request.form.get("out_of_stock_on")))
    flash(t("Avisos salvos."), "success")
    return redirect(url_for("account_notifications"))


@app.route("/account/notifications/subscribe", methods=["POST"])
@login_required
def account_notifications_subscribe():
    blocked = _json_guard()
    if blocked:
        return blocked
    try:
        endpoint, p256dh, auth = push.parse_subscription(request.get_json(silent=True))
    except push.Invalid:
        return jsonify(error=t("O servidor recusou a inscrição.")), 400
    db.save_push_subscription(session["user_id"], endpoint, p256dh, auth,
                              request.headers.get("User-Agent", ""))
    return jsonify(ok=True, devices=len(db.list_push_subscriptions(session["user_id"])))


@app.route("/account/notifications/unsubscribe", methods=["POST"])
@login_required
def account_notifications_unsubscribe():
    """Removes THIS browser's subscription (by endpoint) — only if it is the caller's."""
    blocked = _json_guard()
    if blocked:
        return blocked
    data = request.get_json(silent=True)
    endpoint = data.get("endpoint") if isinstance(data, dict) else None
    if not isinstance(endpoint, str) or not endpoint:
        return jsonify(error=t("Não foi possível desativar.")), 400
    db.delete_push_subscription_by_endpoint(session["user_id"], endpoint)
    return jsonify(ok=True, devices=len(db.list_push_subscriptions(session["user_id"])))


@app.route("/account/notifications/devices/<int:sub_id>/delete", methods=["POST"])
@login_required
@demo_blocked
def account_notifications_device_delete(sub_id):
    if db.delete_push_subscription(session["user_id"], sub_id):
        flash(t("Aparelho removido."), "success")
    return redirect(url_for("account_notifications"))


@app.route("/account/notifications/test", methods=["POST"])
@login_required
def account_notifications_test():
    blocked = _json_guard()
    if blocked:
        return blocked
    results = push.send_to_user(session["user_id"], "Spool", t("Notificação de teste."),
                                url_for("account_notifications"))
    return jsonify(results=[{"device": _device_label(r["kind"]), "result": r["result"],
                             "status": r.get("status")} for r in results])
