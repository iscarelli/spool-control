import os
import re
import json
import time
import uuid
import socket
import secrets
import ipaddress
import urllib.request
import urllib.error
from urllib.parse import urlsplit, urlparse
from functools import wraps
from pathlib import Path
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort, g,
)
from markupsafe import Markup, escape
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
import pyotp
import database as db
import translations as i18n
import logger as log_cfg
from structlog.contextvars import clear_contextvars, bind_contextvars

# Este é o NÚCLEO do app: cria o objeto `app`, configura segurança, logging, helpers,
# decorators e os error handlers. As ROTAS vivem em routes/*.py (agrupadas por assunto)
# e compartilham este mesmo `app`. Os módulos de rota são importados no FINAL deste
# arquivo (ver "Registro das rotas") — isso evita import circular e mantém os nomes de
# endpoint iguais, então nenhum url_for() de template precisa mudar.

BRANDS_DIR = Path(__file__).parent / "static" / "brands"


def _clean_domain(domain: str) -> str:
    domain = re.sub(r'^https?://', '', domain.strip())
    domain = re.sub(r'^www\.', '', domain)
    return domain.split('/')[0].strip()


def _logo_sources(domain: str) -> list[str]:
    return [
        f"https://logo.clearbit.com/{domain}",
        f"https://t3.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://{domain}&size=256",
        f"https://icons.duckduckgo.com/ip3/{domain}.ico",
    ]


# ── Proteção anti-SSRF para downloads externos (logos, release check) ────────
# As URLs de logo embutem um domínio fornecido pelo admin. Os hosts são fixos
# (Clearbit/gstatic/DuckDuckGo), mas urlopen segue redirects por padrão — um 3xx
# poderia levar a um IP interno (169.254.169.254, 10.x, localhost…). Resolvemos o
# host e recusamos qualquer endereço não-público, inclusive a cada redirect.

def _is_public_host(host: str) -> bool:
    """True só se TODOS os IPs resolvidos de `host` forem públicos roteáveis.
    Falha fechada (qualquer erro → False)."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


class _NoRedirectValidating(urllib.request.HTTPRedirectHandler):
    """Revalida o host de destino de cada redirect — bloqueia rebind p/ IP interno."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if parts.scheme not in ("http", "https") or not _is_public_host(parts.hostname):
            return None  # aborta o redirect
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_safe_opener = urllib.request.build_opener(_NoRedirectValidating())


def _safe_urlopen(url: str, timeout: int = 10):
    """urlopen com guarda anti-SSRF: só http/https, host público, e cada redirect
    revalidado. Levanta em esquema/host inválido — chame dentro de try/except."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"esquema não permitido: {parts.scheme!r}")
    if not _is_public_host(parts.hostname):
        raise ValueError(f"host não-público recusado: {parts.hostname!r}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return _safe_opener.open(req, timeout=timeout)


def _try_fetch_image(url: str) -> bytes | None:
    try:
        with _safe_urlopen(url, timeout=10) as resp:
            ct = resp.headers.get('Content-Type', '')
            if resp.status == 200 and ('image' in ct or 'octet' in ct):
                return resp.read()
    except Exception:
        pass
    return None


def _fetch_brand_logo(brand_name: str, domain: str) -> bool:
    BRANDS_DIR.mkdir(exist_ok=True)
    slug = re.sub(r'[^a-z0-9]+', '-', brand_name.lower()).strip('-')
    dest = BRANDS_DIR / f"{slug}.png"
    clean = _clean_domain(domain)
    for url in _logo_sources(clean):
        data = _try_fetch_image(url)
        if data:
            dest.write_bytes(data)
            db.update_brand_logo_path(brand_name, f"brands/{slug}.png")
            log.info("brand_logo.fetched", brand=brand_name, source=url)
            return True
    log.warning("brand_logo.fetch_failed", brand=brand_name, domain=domain)
    return False

app = Flask(__name__)

# Atrás do Traefik: confia em 1 proxy para X-Forwarded-For/Proto/Host.
# Necessário para que request.remote_addr seja o IP real do cliente (rate-limit
# e auditoria) e para request.is_secure refletir o HTTPS terminado no proxy.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# SECRET_KEY é obrigatória em produção: sem ela, cookies de sessão seriam
# assináveis por qualquer um (forja de sessão de admin). Só caímos para um
# valor de dev quando o módulo é executado diretamente (python app.py).
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    if __name__ == "__main__":
        _secret = "dev-only-insecure-key"
    else:
        raise RuntimeError(
            "SECRET_KEY ausente — defina no ambiente (spool.env) antes de iniciar."
        )
app.secret_key = _secret

DEMO_MODE = os.environ.get("DEMO_MODE", "0") == "1"

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SECURE_COOKIES", "0") == "1",
    # Duração do cookie quando o usuário marca "Manter conectado" (30 dias).
    # Sem marcar, a sessão vira cookie de sessão (expira ao fechar o navegador) —
    # ver login(): session.permanent = bool(remember).
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
    MAX_CONTENT_LENGTH=64 * 1024 * 1024,  # 64 MB — headroom p/ restore de backup (zip: DB + logos); ainda limitado (anti-DoS)
    WTF_CSRF_TIME_LIMIT=None,             # token válido enquanto a sessão durar
)

# Proteção CSRF global em todos os POST/PUT/PATCH/DELETE.
csrf = CSRFProtect(app)

# Janela e limite do throttle de login (anti força-bruta), por IP.
LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW_MIN = 15

# Tamanho mínimo de senha no cadastro/troca de usuário. O rate-limit acima cobre
# a força-bruta online; isto barra senhas triviais na origem.
MIN_PASSWORD_LEN = 8

log_cfg.configure_logging(app)
log = log_cfg.get_logger()


@app.before_request
def _req_start():
    clear_contextvars()
    rid = uuid.uuid4().hex[:8]
    bind_contextvars(
        request_id=rid,
        method=request.method,
        path=request.path,
        ip=request.remote_addr,
        user=session.get("username", "anon"),
    )
    g._request_id = rid
    g._nonce = secrets.token_urlsafe(16)
    g._t0 = time.perf_counter()


@app.before_request
def _validate_session():
    """Revogação de sessão server-side (CWE-613). O cookie de sessão do Flask é
    *stateless* (assinado), então `session.clear()` no logout só apaga o cookie do
    navegador — um cookie capturado continuaria válido até expirar. Aqui amarramos
    cada sessão a um `session_token` guardado no usuário: o login grava o token na
    sessão e toda requisição autenticada revalida contra o banco. Logout e troca de
    senha ROTACIONAM o token, invalidando imediatamente quaisquer cookies antigos.

    Cookies legados (anteriores a esta versão, sem `auth_token`) não batem com o
    token recém-semeado → a sessão é encerrada uma única vez e o usuário reloga."""
    if request.endpoint in ("static", "health") or "user_id" not in session:
        return
    stored = db.get_session_token(session["user_id"])
    if not stored or session.get("auth_token") != stored:
        session.clear()
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(error="Unauthorized"), 401
        return redirect(url_for("login"))


# Endpoints liberados mesmo com troca de senha pendente (o próprio formulário,
# trocar idioma, sair, assets e o health-check).
_PWCHANGE_ALLOWED = {"account_password", "logout", "set_lang", "static", "health"}


@app.before_request
def _force_password_change():
    """Se o usuário logado tem senha temporária pendente, prende-o no formulário de
    troca até definir uma senha própria. Desligado no DEMO_MODE."""
    if DEMO_MODE or "user_id" not in session:
        return
    if not session.get("must_change_password"):
        return
    if request.endpoint in _PWCHANGE_ALLOWED:
        return
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(error="password_change_required"), 403
    return redirect(url_for("account_password"))


@app.after_request
def set_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    nonce = getattr(g, "_nonce", "")
    # Assets do Bootstrap/Bootstrap Icons são servidos same-origin (static/vendor/),
    # então o CSP não confia em nenhum CDN externo. 'unsafe-inline' em style-src
    # permanece pelos estilos inline dos templates.
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "font-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.is_secure:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    rid = getattr(g, "_request_id", None)
    if rid:
        resp.headers["X-Request-ID"] = rid
    t0 = getattr(g, "_t0", None)
    if t0 is not None:
        log.info("request", status=resp.status_code,
                 duration_ms=round((time.perf_counter() - t0) * 1000, 1))
    return resp


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(error="CSRF token inválido ou ausente"), 400
    flash(t("Sessão expirada ou token inválido. Tente novamente."), "danger")
    return redirect(request.referrer or url_for("login")), 400


# ── Bootstrap ──────────────────────────────────────────────────────────────

def bootstrap():
    db.init_db()
    if DEMO_MODE:
        # Guard-rail: MODO DEMO desabilita troca de senha/criação de usuários e os dados
        # podem ser reiniciados. Nunca deve estar ligado numa instalação real — gritamos
        # no journal (além do banner em toda página e do /health) p/ flagrar um vazamento.
        log.warning(
            "demo_mode.enabled",
            note="Instância em MODO DEMONSTRATIVO — NÃO use em produção. "
                 "Defina DEMO_MODE=0 em spool.env para uma instalação real.",
        )
    default_pass = os.environ.get("ADMIN_DEFAULT_PASS")
    if not default_pass:
        default_pass = secrets.token_urlsafe(12)
        log.warning("admin.ephemeral_password", password=default_pass,
                    note="Define ADMIN_DEFAULT_PASS em spool.env para suprimir este aviso")
    # Em produção o admin é obrigado a trocar a senha inicial no 1º login (a senha
    # aleatória vai para o journal). No DEMO_MODE a senha é fixa e a troca é desabilitada.
    db.ensure_admin_user("admin", generate_password_hash(default_pass),
                         must_change=not DEMO_MODE)
    # Chaves de API por integração (independentes — rotacionar uma não afeta a outra).
    # A da balança herda a SPOOL_API_KEY do ambiente p/ NÃO quebrar installs existentes;
    # a do Home Assistant nasce gerada (read-only). Geridas em Admin → Integrações.
    db.ensure_api_key("scale", scope="write", label="Balança / estação de pesagem",
                      key=os.environ.get("SPOOL_API_KEY", "").strip() or None)
    db.ensure_api_key("homeassistant", scope="read", label="Home Assistant")


bootstrap()

VERSION_FILE = Path(__file__).parent / "VERSION"
APP_VERSION = VERSION_FILE.read_text().strip()

# ── Autoatualização: checagem da última release no GitHub ────────────────────
RELEASES_URL = "https://github.com/iscarelli/spool-control/releases"
# A DETECÇÃO de versão usa o redirect de .../releases/latest (o SITE, não a REST
# API) → imune ao limite anônimo de 60/h por IP, que qualquer cliente da mesma
# rede pode esgotar. A REST API só entra para as NOTAS da release, e somente na
# página /admin/update (latest_release_notes), de forma tolerante a falha.
GITHUB_LATEST_RELEASE = RELEASES_URL + "/latest"
GITHUB_RELEASES_API = "https://api.github.com/repos/iscarelli/spool-control/releases/latest"
# CHANGELOG cru na tag mais recente — fonte das notas ACUMULADAS (várias versões
# atrás). É o CDN raw (sem o limite de 60/h da REST API) e traz o histórico por versão.
GITHUB_CHANGELOG_RAW = "https://raw.githubusercontent.com/iscarelli/spool-control/{tag}/CHANGELOG.md"

# Cache em memória (por worker). Sucesso vale 6h; falha re-tenta em 15min; um
# debounce de 30s evita martelar em refreshes seguidos. Fail-open: erro nunca
# quebra a página, só não mostra atualização.
_release_cache = {"tag": None, "ts": 0.0, "ok": False}
_notes_cache = {"tag": None, "notes": ""}
_cumulative_cache = {"key": None, "notes": ""}
_RELEASE_TTL_OK = 6 * 3600
_RELEASE_TTL_FAIL = 15 * 60
_RELEASE_DEBOUNCE = 30


class _CaptureRedirect(urllib.request.HTTPRedirectHandler):
    """Não SEGUE o redirect — deixa o 3xx propagar para lermos só o cabeçalho
    Location. Como não buscamos o destino, não há risco de SSRF aqui."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_redirect_reader = urllib.request.build_opener(_CaptureRedirect())


def _version_tuple(v):
    parts = re.findall(r"\d+", v or "")
    return tuple(int(p) for p in parts) if parts else (0,)


def current_version():
    """Lê o VERSION do disco na hora — reflete um update já aplicado mesmo antes
    de o processo ser reiniciado (a constante APP_VERSION é fixada no import)."""
    try:
        return VERSION_FILE.read_text().strip()
    except Exception:
        return APP_VERSION


def _latest_release_tag_via_web():
    """Última tag pelo redirect de github.com/.../releases/latest — o SITE, não a
    REST API (logo, sem o limite de 60/h). Lê o Location do 302
    (.../releases/tag/vX.Y.Z) SEM seguir o redirect. Devolve a tag ('v1.31.0') ou
    levanta."""
    if not _is_public_host(urlsplit(GITHUB_LATEST_RELEASE).hostname):
        raise ValueError("host do GitHub não-público")
    req = urllib.request.Request(GITHUB_LATEST_RELEASE,
                                 headers={"User-Agent": "spool-control"})
    location = ""
    try:
        with _redirect_reader.open(req, timeout=4) as resp:
            location = resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            location = e.headers.get("Location", "")
        else:
            raise
    if "/tag/" not in location:
        raise ValueError(f"redirect inesperado: {location!r}")
    return location.rstrip("/").rsplit("/tag/", 1)[-1]


def check_latest_release(max_age=None):
    """Última tag publicada (sem o 'v') via o redirect do site — SEM REST API, logo
    sem o limite de 60/h. Cacheada; um debounce de 30s evita martelar em refreshes.
    max_age (s): idade máxima aceitável do cache antes de re-consultar (a página de
    update passa um valor curto); None usa o TTL padrão (6h ok / 15min falha)."""
    now = time.time()
    age = (now - _release_cache["ts"]) if _release_cache["ts"] else None
    if age is not None:
        if age < _RELEASE_DEBOUNCE:                      # anti-martelo (sempre)
            return _release_cache["tag"]
        limit = max_age if max_age is not None else (
            _RELEASE_TTL_OK if _release_cache["ok"] else _RELEASE_TTL_FAIL)
        if age < limit:
            return _release_cache["tag"]
    try:
        tag = _latest_release_tag_via_web().lstrip("v").strip()
        _release_cache.update(tag=tag or _release_cache["tag"], ts=now, ok=bool(tag))
    except Exception:
        _release_cache.update(ts=now, ok=False)
        log.warning("github_release.check_failed", exc_info=True)
    return _release_cache["tag"]


def cached_latest_tag():
    """Última tag conhecida do cache, SEM tocar a rede — para o badge do menu, que
    NÃO deve disparar consulta fora da página de atualização (quem popula o cache é
    a /admin/update). None se ainda não buscou com sucesso."""
    return _release_cache["tag"] if _release_cache["ok"] else None


def latest_release_notes():
    """Notas (Markdown) da última release, via REST API — chamada SÓ na página de
    update. Tolerante a falha (rate limit 60/h por IP / sem rede / timeout): em vez
    de zerar, **reusa a última nota obtida com sucesso**, para o card "Ver novidades"
    não cair pro link do GitHub por uma falha pontual da API. Só devolve '' (→ link)
    se NUNCA conseguimos notas. Cacheada pela tag corrente."""
    tag = _release_cache.get("tag")
    if not tag:
        return _notes_cache["notes"]
    if _notes_cache["tag"] == tag and _notes_cache["notes"]:
        return _notes_cache["notes"]
    try:
        if not _is_public_host(urlsplit(GITHUB_RELEASES_API).hostname):
            raise ValueError("host da API do GitHub não-público")
        req = urllib.request.Request(
            GITHUB_RELEASES_API,
            headers={"User-Agent": "spool-control", "Accept": "application/vnd.github+json"},
        )
        with _safe_opener.open(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        notes = (data.get("body") or "").strip()
        if notes:
            _notes_cache.update(tag=tag, notes=notes)
            return notes
    except Exception:
        log.info("github_release.notes_unavailable", exc_info=True)
    # fail-open: mantém a última nota boa (mesmo que de outra tag) p/ o card sobreviver
    # a uma falha pontual; '' só quando nunca obtivemos notas → cai pro link.
    return _notes_cache["notes"]


def _changelog_md(tag):
    """Baixa o CHANGELOG.md cru na tag `tag` (ex.: 'v1.38.0'). Levanta em falha —
    chame dentro de try/except. Isolado numa função p/ os testes monkeypatcharem."""
    url = GITHUB_CHANGELOG_RAW.format(tag=tag)
    if not _is_public_host(urlsplit(url).hostname):
        raise ValueError("host do raw.githubusercontent não-público")
    req = urllib.request.Request(url, headers={"User-Agent": "spool-control"})
    with _safe_opener.open(req, timeout=8) as resp:
        return resp.read().decode()


def _slice_changelog(md, current, latest):
    """Extrai do CHANGELOG as seções de versão em (current, latest] — o que há de
    novo entre a versão instalada (exclusive) e a última (inclusive). Devolve o
    markdown concatenado (mais nova primeiro, como no arquivo) ou '' se nada casar."""
    cur_t, lat_t = _version_tuple(current), _version_tuple(latest)
    header_re = re.compile(r"^##\s+\[(\d+\.\d+\.\d+)\]")
    sections, ver, buf = [], None, []
    for ln in (md or "").replace("\r\n", "\n").split("\n"):
        m = header_re.match(ln)
        if m:
            if ver is not None:
                sections.append((ver, buf))
            ver, buf = m.group(1), [ln]
        elif ver is not None:
            buf.append(ln)
    if ver is not None:
        sections.append((ver, buf))
    kept = [buf for v, buf in sections if cur_t < _version_tuple(v) <= lat_t]
    return "\n".join(ln for buf in kept for ln in buf).strip()


def cumulative_release_notes():
    """Notas ACUMULADAS para o card "Ver novidades": todas as seções do CHANGELOG
    entre a versão instalada (exclusive) e a última publicada (inclusive) — assim
    quem está várias versões atrás vê o histórico todo, não só a última. Fonte: o
    CHANGELOG.md cru na tag latest. Fail-open: sem tag, ou se a busca/parse falhar
    ou nada casar, cai nas notas da última release (comportamento anterior).

    Devolve (notes, complete): `complete` é True só quando `notes` veio de fatiar
    o CHANGELOG de verdade; é False em todo caminho de fallback (sem tag, busca
    falhou, ou o corte não achou nada) — quem chama usa isso para avisar que o
    histórico mostrado pode estar incompleto."""
    tag = _release_cache.get("tag")
    current = current_version()
    if not tag:
        return latest_release_notes(), False
    key = (current, tag)
    if _cumulative_cache["key"] == key and _cumulative_cache["notes"]:
        return _cumulative_cache["notes"], True
    try:
        notes = _slice_changelog(_changelog_md(f"v{tag}"), current, tag)
        if notes:
            _cumulative_cache.update(key=key, notes=notes)
            return notes, True
    except Exception:
        log.info("github_changelog.unavailable", exc_info=True)
    return latest_release_notes(), False


_current_notes_cache = {"version": None, "notes": ""}


def _version_just_below(version):
    """String cujo _version_tuple compara MENOR que o de `version`, mas maior que
    qualquer versão anterior real publicada — usado como limite inferior exclusivo
    em _slice_changelog p/ isolar só a seção da própria `version` (decrementa o
    componente mais à direita com folga; toma emprestado do componente à esquerda
    quando ele já é 0, sem nunca produzir um número negativo)."""
    t = list(_version_tuple(version))
    while len(t) < 3:
        t.append(0)
    major, minor, patch = t[0], t[1], t[2]
    if patch > 0:
        return f"{major}.{minor}.{patch - 1}"
    if minor > 0:
        return f"{major}.{minor - 1}.999999"
    if major > 0:
        return f"{major - 1}.999999.999999"
    return "0.0.0"


def current_release_notes():
    """Notas do CHANGELOG só da versão JÁ INSTALADA — para quem está em dia poder
    reler o que mudou nesta versão mesmo sem update pendente (a página de update
    só mostra o card acumulado quando `latest` é mais nova que `current`). Fonte:
    o CHANGELOG.md cru na tag da PRÓPRIA versão instalada. Reusa _slice_changelog
    (latest=current, limite inferior logo abaixo via _version_just_below) — não
    duplica o parser nem o renderizador. Fail-open: tag inexistente, rede fora do
    ar, ou nada casado → '' (o template cai pro link do GitHub). Cacheada por
    versão instalada, como cumulative_release_notes cacheia por (current, tag)."""
    current = current_version()
    if _current_notes_cache["version"] == current and _current_notes_cache["notes"]:
        return _current_notes_cache["notes"]
    try:
        md = _changelog_md(f"v{current}")
        notes = _slice_changelog(md, _version_just_below(current), current)
        if notes:
            _current_notes_cache.update(version=current, notes=notes)
            return notes
    except Exception:
        log.info("github_changelog.current_unavailable", exc_info=True)
    return ""


def notes_incomplete_warning(complete, current, latest):
    """Decide se vale mostrar o aviso de "histórico pode estar incompleto":
    só quando `complete` é False (cumulative_release_notes caiu no fallback) E o
    salto não é um patch único logo acima da instalada (mesmo major.minor,
    latest_patch - current_patch == 1) — nesse caso a nota da última release JÁ
    é a história inteira, e o aviso seria só ruído."""
    if complete:
        return False
    cur_t, lat_t = _version_tuple(current), _version_tuple(latest)
    if (len(cur_t) >= 3 and len(lat_t) >= 3
            and cur_t[0] == lat_t[0] and cur_t[1] == lat_t[1]
            and lat_t[2] - cur_t[2] == 1):
        return False
    return True


# Subconjunto de Markdown usado nas release notes → HTML seguro, sem dependência
# externa. Escapa TUDO primeiro (anti-XSS) e só então insere as tags de formatação,
# então um `body` malicioso vindo do GitHub não consegue injetar HTML.
def render_release_notes(md):
    def inline(s):
        s = str(escape(s))
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                   r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
        return s

    out, tbl, ul = [], [], []   # `ul` = pilha de <ul> abertas (suporta aninhamento)

    def close_ul(to=0):
        while len(ul) > to:
            out.append("</ul>"); ul.pop()

    def flush_tbl():
        if not tbl:
            return
        rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in tbl]
        body = [r for r in rows if not all(c and set(c) <= set("-: ") for c in r)]
        tbl.clear()
        if not body:
            return
        head, rest = body[0], body[1:]
        out.append('<table class="table table-sm small mb-2">')
        out.append("<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead>")
        if rest:
            out.append("<tbody>" + "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rest
            ) + "</tbody>")
        out.append("</table>")

    for raw in (md or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        stripped = line.lstrip()
        if stripped.startswith("|") and "|" in stripped[1:]:
            close_ul(); tbl.append(line); continue
        flush_tbl()
        if not stripped:
            close_ul(); continue
        if stripped.startswith("### "):
            close_ul(); out.append(f"<div class='fw-semibold mt-2'>{inline(stripped[4:])}</div>")
        elif stripped.startswith("## "):
            close_ul(); out.append(f"<div class='fw-bold mt-2'>{inline(stripped[3:])}</div>")
        elif stripped.startswith("# "):
            close_ul(); out.append(f"<div class='fw-bold mt-2'>{inline(stripped[2:])}</div>")
        elif re.match(r"^[-*] ", stripped):
            # Nível pela indentação (cada ~2 espaços = um nível) → sub-listas aninhadas.
            level = (len(line) - len(stripped)) // 2 + 1
            while len(ul) < level:
                out.append("<ul class='mb-2 ps-3'>"); ul.append(True)
            close_ul(level)
            out.append(f"<li>{inline(re.sub(r'^[-*] ', '', stripped))}</li>")
        elif stripped.startswith("> "):
            close_ul(); out.append(f"<p class='text-muted border-start ps-2 mb-1'>{inline(stripped[2:])}</p>")
        else:
            close_ul(); out.append(f"<p class='mb-1'>{inline(line)}</p>")
    close_ul(); flush_tbl()
    return Markup("\n".join(out))


def is_update_available():
    """Badge do menu Admin: lê SÓ o cache (sem rede) — nunca dispara consulta fora
    da página de atualização, que é quem popula o cache."""
    latest = cached_latest_tag()
    return bool(latest) and _version_tuple(latest) > _version_tuple(current_version())

ALL_MATERIALS = [
    "ABS", "ABS+", "ABS-CF",
    "ASA", "ASA-CF",
    "BVOH",
    "CPE", "CPE+",
    "FLEX",
    "HIPS",
    "NYLON", "NYLON-CF", "NYLON-GF",
    "PA", "PA6", "PA6-CF", "PA11", "PA11-CF", "PA12", "PA12-CF",
    "PEBA", "PEBA-CF",
    "PC", "PC-ABS", "PC-CF",
    "PEEK", "PEEK-CF",
    "PEI",
    "PETG", "PETG-CF",
    "PLA", "PLA+", "PLA-CF", "PLA-HT", "PLA-ST",
    "PMMA",
    "PP", "PP-CF", "PP-GF",
    "PPS",
    "PVA",
    "SBS",
    "SILK",
    "TPE",
    "TPU", "TPU-CF",
    "Compósito", "Outro",
]


def get_ordered_materials():
    in_use = set(db.get_materials_in_use())
    used = sorted([m for m in ALL_MATERIALS if m in in_use])
    extra = sorted([m for m in in_use if m not in set(ALL_MATERIALS)])
    unused = sorted([m for m in ALL_MATERIALS if m not in in_use])
    return used + extra + unused


_CURRENCY_META = {
    "BRL": {"symbol": "R$", "decimal": ",", "thousands": "."},
    "USD": {"symbol": "$",  "decimal": ".", "thousands": ","},
    "EUR": {"symbol": "€",  "decimal": ",", "thousands": "."},
    "CAD": {"symbol": "C$", "decimal": ".", "thousands": ","},
}


def _currency_meta():
    code = db.get_setting("currency", "BRL")
    return _CURRENCY_META.get(code, _CURRENCY_META["BRL"])


def _format_price(value):
    if value is None:
        return ""
    meta = _currency_meta()
    # Formata com 2 casas decimais usando os separadores da moeda configurada.
    int_part, dec_part = f"{value:.2f}".split(".")
    # Insere separador de milhar
    n = len(int_part)
    groups = []
    while n > 3:
        groups.insert(0, int_part[n-3:n])
        n -= 3
    groups.insert(0, int_part[:n])
    return meta["thousands"].join(groups) + meta["decimal"] + dec_part


def _parse_price(s):
    if not s:
        return None
    s = s.strip()
    meta = _currency_meta()
    s = s.replace(meta["symbol"], "").strip()
    if meta["decimal"] == ",":
        # Formato BR/EUR: ponto = milhar, vírgula = decimal
        s = s.replace(".", "").replace(",", ".")
    else:
        # Formato USD: vírgula = milhar, ponto = decimal
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def t(s):
    """Traduz uma string conforme o idioma da sessão — para mensagens flash e de
    erro geradas no servidor (fora do template)."""
    return i18n.get_translator(session.get("lang", "pt"))(s)


def _safe_next(url, default=""):
    """Aceita só caminhos relativos ao próprio site — evita open redirect.

    Rejeita URLs absolutas (com esquema ou host) e barras invertidas: vários
    navegadores normalizam "\\" para "/", então "/\\evil.com" viraria
    "//evil.com" (host externo) e escaparia de um teste ingênuo de prefixo."""
    if not url or "\\" in url:
        return default
    parts = urlsplit(url)
    if parts.scheme or parts.netloc:
        return default
    if url.startswith("/") and not url.startswith("//"):
        return url
    return default


@app.context_processor
def inject_globals():
    count = db.queue_count() if "user_id" in session else 0
    lang = session.get("lang", "pt")
    is_admin = session.get("role") == "admin"
    # Espelha o gate server-side (write_required/WRITE_ROLES) na UI: esconde botões de
    # escrita p/ `viewer`. É só defesa em profundidade — quem barra de verdade é o servidor.
    can_write = session.get("role") in WRITE_ROLES
    # Alerta de backup (só admin): última rotação diária falhou ou a cópia externa falhou.
    backup_alert = bool(is_admin and (
        db.get_setting("backup_last_result", "") == "error"
        or db.get_setting("backup_external_error", "")
    ))
    return {
        "label_queue_count": count,
        "app_version": APP_VERSION,
        "lang": lang,
        "_": i18n.get_translator(lang),
        "update_available": is_update_available() if is_admin else False,
        "can_write": can_write,
        "is_admin": is_admin,
        "backup_alert": backup_alert,
        "nonce": getattr(g, "_nonce", ""),
        "demo_mode": DEMO_MODE,
        "currency": _currency_meta(),
        "format_price": _format_price,
    }


# ── Formatação de data conforme o idioma ─────────────────────────────────────

def _parse_dt(value):
    if not value:
        return None
    s = str(value).strip().replace("T", " ").split(".")[0].split("+")[0].rstrip("Z").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


@app.template_filter("localdt")
def localdt(value):
    """Data + hora no formato do idioma atual (pt: dd/mm/aaaa HH:MM)."""
    dt = _parse_dt(value)
    if not dt:
        return value or ""
    fmt = "%d/%m/%Y %H:%M" if session.get("lang", "pt") == "pt" else "%m/%d/%Y %H:%M"
    return dt.strftime(fmt)


@app.template_filter("localdate")
def localdate(value):
    """Apenas a data, no formato do idioma atual (pt: dd/mm/aaaa)."""
    dt = _parse_dt(value)
    if not dt:
        return value or ""
    fmt = "%d/%m/%Y" if session.get("lang", "pt") == "pt" else "%m/%d/%Y"
    return dt.strftime(fmt)


_HEX_COLOR_RE = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")


@app.template_filter("hexcolor")
def hexcolor(value, default=""):
    """Sanitiza uma cor vinda do banco ANTES de injetá-la em `style=`/SVG. `color_hex`
    é campo de texto livre no cadastro de filamento; sem isso, um valor tipo
    `red;background:url(...)` faria CSS injection dentro do atributo (o autoescape do
    Jinja barra a saída do atributo, mas não a injeção de propriedades). Só passa um
    #RGB/#RRGGBB válido; qualquer outra coisa vira `default`."""
    v = (value or "").strip()
    return v if _HEX_COLOR_RE.match(v) else default


@app.route("/lang/<code>")
def set_lang(code):
    if code in i18n.SUPPORTED:
        session["lang"] = code
    return redirect(request.referrer or url_for("dashboard"))


# ── Auth decorators ────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(error="Unauthorized"), 401
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        if session.get("role") != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


# Papéis com permissão de ESCRITA no inventário (criar/editar/excluir/pesar spools,
# filamentos e modelos). `viewer` é somente-leitura — o rótulo no cadastro de usuário
# é literalmente "Viewer (somente leitura)", então a regra é enforçada no servidor,
# não só escondendo botões. Fica numa constante p/ facilitar um futuro papel "editor".
WRITE_ROLES = ("admin",)


def write_required(f):
    """Exige um papel com permissão de escrita (CWE-285). Aplicado em TODA rota que
    muta dados do inventário — o gate é no servidor, independente da UI."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(error="Unauthorized"), 401
            return redirect(url_for("login", next=request.path))
        if session.get("role") not in WRITE_ROLES:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def demo_blocked(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if DEMO_MODE:
            flash(t("Função desabilitada na versão demonstrativa."), "warning")
            return redirect(request.referrer or url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# ── Auth ───────────────────────────────────────────────────────────────────

def _promote_session(user, remember, ip, next_url=""):
    """Abre a sessão completa após autenticação bem-sucedida (senha + 2FA, se houver).
    Centraliza o que login() e login_2fa() precisam gravar."""
    session.permanent = bool(remember)
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    session["must_change_password"] = bool(user["must_change_password"])
    # Amarra o cookie a um token server-side (ver _validate_session): permite revogar
    # esta sessão no logout / troca de senha rotacionando o token no banco.
    session["auth_token"] = db.get_or_create_session_token(user["id"])
    db.log_login(user["username"], ip)
    # Open redirect (CWE-601): valida o destino no PRÓPRIO ponto do redirect (o
    # analisador não reconhece a barreira interprocedural do _safe_next). Segue
    # EXATAMENTE o snippet recomendado pelo CodeQL para py/url-redirection:
    # navegadores tratam "\" como "/", então remove as barras invertidas e checa
    # `urlparse(target).netloc`/`.scheme` inline — caminho relativo é seguro.
    # Exige um caminho relativo de verdade (começa com "/" mas não "//"): sem
    # `next`, target="" passaria no teste de netloc/scheme e cairia num
    # `redirect("")`, que recarrega a própria /login (regressão da v1.31.0).
    target = (next_url or "").replace("\\", "")
    if target.startswith("/") and not target.startswith("//") \
            and not urlparse(target).netloc and not urlparse(target).scheme:
        return redirect(target)
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr or ""
        if db.count_recent_login_failures(ip, LOGIN_WINDOW_MIN) >= LOGIN_MAX_FAILURES:
            flash(
                t("Muitas tentativas. Aguarde {min} minutos e tente novamente.").format(min=LOGIN_WINDOW_MIN),
                "danger",
            )
            return render_template("login.html"), 429
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.get_user_by_username(username)
        if user and check_password_hash(user["password_hash"], password):
            db.clear_login_failures(ip)
            remember = bool(request.form.get("remember"))
            nxt = request.args.get("next") or ""
            # 2FA ligado: NÃO abre sessão ainda — guarda estado pré-auth e manda
            # para o segundo passo. O estado "pré-2FA" não é sessão válida, então
            # qualquer outra rota continua caindo no login_required.
            if user["totp_enabled"]:
                session["pre2fa_user_id"] = user["id"]
                session["pre2fa_remember"] = remember
                session["pre2fa_next"] = _safe_next(nxt)
                return redirect(url_for("login_2fa"))
            # "Manter conectado": cookie persistente (30 dias). Sem marcar,
            # cookie de sessão que expira ao fechar o navegador.
            return _promote_session(user, remember, ip, nxt)
        db.record_login_failure(ip, username)
        flash(t("Usuário ou senha incorretos"), "danger")
    return render_template("login.html")


@app.route("/login/2fa", methods=["GET", "POST"])
def login_2fa():
    """Segundo passo do login quando o usuário tem 2FA ativo. Aceita um código TOTP
    (6 dígitos) OU um código de recuperação one-time. Sem estado pré-2FA → volta ao login."""
    uid = session.get("pre2fa_user_id")
    if not uid:
        return redirect(url_for("login"))
    user = db.get_user_by_id(uid)
    if not user or not user["totp_enabled"]:
        session.pop("pre2fa_user_id", None)
        return redirect(url_for("login"))
    if request.method == "POST":
        ip = request.remote_addr or ""
        # Mesmo throttle por IP da senha — barra brute-force dos 6 dígitos.
        if db.count_recent_login_failures(ip, LOGIN_WINDOW_MIN) >= LOGIN_MAX_FAILURES:
            flash(
                t("Muitas tentativas. Aguarde {min} minutos e tente novamente.").format(min=LOGIN_WINDOW_MIN),
                "danger",
            )
            return render_template("login_2fa.html"), 429
        code = request.form.get("code", "").strip().replace(" ", "")
        totp = pyotp.TOTP(user["totp_secret"])
        ok = totp.verify(code, valid_window=1) or db.consume_recovery_code(uid, code)
        if ok:
            db.clear_login_failures(ip)
            remember = bool(session.pop("pre2fa_remember", False))
            nxt = session.pop("pre2fa_next", "") or ""
            session.pop("pre2fa_user_id", None)
            log.info("auth.2fa_ok")
            return _promote_session(user, remember, ip, nxt)
        db.record_login_failure(ip, user["username"])
        log.warning("auth.2fa_fail")
        flash(t("Código inválido"), "danger")
    return render_template("login_2fa.html")


@app.route("/logout", methods=["POST"])
def logout():
    # Rotaciona o token server-side ANTES de limpar o cookie: invalida na hora
    # qualquer outra cópia deste cookie de sessão (replay pós-logout — CWE-613).
    uid = session.get("user_id")
    if uid:
        db.rotate_session_token(uid)
    session.clear()
    return redirect(url_for("login"))


# ── Helpers de etiqueta (usados pelos módulos spools e label_queue) ──────────

def public_base_url():
    """URL pública base p/ QR/etiquetas. A setting do banco manda; se ausente ou
    ainda no default localhost, cai no APP_BASE_URL do ambiente (definido na
    instalação). Garante que cada instalação use a própria URL pública — o QR da
    pesagem automática depende disso (ver docs/estudo_balanca_qrcode.md)."""
    url = (db.get_setting("app_base_url", "") or "").strip()
    if not url or url == "http://localhost:5000":
        env = (os.environ.get("APP_BASE_URL", "") or "").strip()
        if env:
            return env
    return url or "http://localhost:5000"


def _label_spool(spool):
    """Dict do spool enriquecido p/ a etiqueta: caminho do logo em disco + nome da cor.
    Usa color_name do filamento se preenchido; senão classifica pelo hex."""
    d = dict(spool)
    rel = d.get("brand_logo")
    p = os.path.join(app.static_folder, rel) if rel else None
    d["logo_file"] = p if (p and os.path.exists(p)) else None
    filament_color_name = (d.get("color_name") or "").strip()
    if filament_color_name:
        d["color_name"] = filament_color_name
    else:
        cn = db.classify_color(d.get("color_hex"))
        d["color_name"] = t(cn) if cn else ""
    return d


# ── Error handlers ─────────────────────────────────────────────────────────

@app.errorhandler(400)
def err_400(e):
    log.warning("http.400", detail=str(e))
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(ok=False, error="bad_request"), 400
    return render_template("error.html", code=400, message=t("Requisição inválida")), 400


@app.errorhandler(403)
def err_403(e):
    log.warning("http.403", path=request.path)
    return render_template("error.html", code=403, message=t("Acesso negado")), 403


@app.errorhandler(404)
def err_404(e):
    return render_template("error.html", code=404, message=t("Página não encontrada")), 404


@app.errorhandler(405)
def err_405(e):
    # Método errado numa rota válida (ex.: GET em /logout, que é POST-only). Sem este
    # handler, o errorhandler(Exception) abaixo capturaria o 405 e o transformaria em
    # 500 — ver `err_unhandled`, que repassa HTTPException justamente por isso.
    log.warning("http.405", path=request.path, method=request.method)
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(ok=False, error="method_not_allowed"), 405
    return render_template("error.html", code=405, message=t("Método não permitido")), 405


@app.errorhandler(422)
def err_422(e):
    log.warning("http.422", detail=str(e))
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(ok=False, error="unprocessable_entity"), 422
    return render_template("error.html", code=422, message=t("Requisição inválida")), 422


@app.errorhandler(500)
def err_500(e):
    log.error("http.500", exc_info=True)
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(ok=False, error="internal_error"), 500
    return render_template("error.html", code=500, message=t("Erro interno do servidor")), 500


@app.errorhandler(Exception)
def err_unhandled(e):
    # HTTPExceptions (404/405/403/abort(...) etc.) NÃO são falhas internas: repassa
    # para o handler específico / resposta padrão do Flask. Sem isto, um simples 405
    # (método errado) viraria 500. Só erros realmente não tratados caem como 500.
    if isinstance(e, HTTPException):
        return e
    log.critical("unhandled_exception", exc=str(e), exc_info=True)
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(ok=False, error="internal_error"), 500
    return render_template("error.html", code=500, message=t("Erro interno do servidor")), 500


# ── Registro das rotas ───────────────────────────────────────────────────────
# Importa os módulos de rota DEPOIS de tudo acima estar definido. Cada um faz
# `from app import app, ...` e registra suas rotas com @app.route — então este import
# é o que "liga" as rotas ao app. Importar aqui (e não no topo) evita import circular.
from routes import (  # noqa: E402
    main, filaments, spool_models, spools, label_queue, reports, admin, api, account,  # noqa: F401
    integrations,  # noqa: F401
)


if __name__ == "__main__":
    # Bloco só de desenvolvimento local — em produção a app sobe via gunicorn
    # (`app:app`), nunca por aqui. debug/host/porta vêm do ambiente; o default é
    # SEM debug e ligado só ao localhost, para não expor o reloader/console nem
    # abrir a porta na rede (CWE-489 / py/flask-debug).
    app.run(
        debug=os.environ.get("FLASK_DEBUG") == "1",
        host=os.environ.get("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_RUN_PORT", "5000")),
    )
