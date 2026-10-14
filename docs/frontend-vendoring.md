# Assets de frontend (Bootstrap + Bootstrap Icons + jsQR)

Código: deploy/vendor-frontend.sh, static/vendor/, static/qr-scan.js, templates/_qr_scan_modal.html, templates/base.html

O app usa **Bootstrap** (CSS + JS) e **Bootstrap Icons** (fonte de ícones). Esses arquivos
são **vendorados** em `static/vendor/` e servidos **same-origin** — não há CDN no carregamento
das páginas.

## Por que vendorar (igual ao Niimbot e ao SpoolmanDB)

O servidor de produção clona o repo **público anonimamente**, e queremos manter o deploy à
prova de falhas, o **CSP estrito** e a **operação offline**. Por isso os assets **não** são
baixados de um CDN em runtime/deploy — o que está no git é o que roda.

Consequência direta no **CSP** (`app.py` → `set_security_headers`): como nada vem de fora, a
política é `default-src 'self'` **sem** `cdn.jsdelivr.net` em `script-src`/`style-src`/`font-src`.
Adicionar um `<link>`/`<script>` apontando para um CDN **quebraria** o CSP — vendore em vez disso.

> Trade-off consciente: ao sair do CDN, perde-se o "auto-update" implícito dele. A atualização
> do Bootstrap passa a ser **manual e deliberada** (ver abaixo). O **Dependabot não vê** esses
> assets (não são pacotes gerenciados), assim como já não vê os outros vendorados.

## Atualizar os assets

As versões ficam **fixadas no topo** do script (`deploy/vendor-frontend.sh`):

```bash
BS_VER="5.3.3"   # Bootstrap
BI_VER="1.11.3"  # Bootstrap Icons
JSQR_VER="1.4.0" # jsQR (decodificador de QR, fallback do iOS)
```

Para subir de versão:

```bash
# 1. edite BS_VER / BI_VER no script
deploy/vendor-frontend.sh        # baixa do jsdelivr p/ static/vendor/ e regrava VENDORED.txt
# 2. revisar git diff, bump VERSION + CHANGELOG, commit, deploy
```

A fonte do Bootstrap Icons é referenciada pelo CSS via caminho **relativo** (`fonts/...`), então
os `.woff2`/`.woff` precisam ficar em `static/vendor/bootstrap-icons/fonts/` — o script já cuida disso.

## Arquivos

| Arquivo | Papel |
|---|---|
| `deploy/vendor-frontend.sh` | Re-vendora os assets a partir do jsdelivr, em versões fixas (manual) |
| `static/vendor/bootstrap/bootstrap.min.css` | Bootstrap CSS (vendorado — não editar) |
| `static/vendor/bootstrap/bootstrap.bundle.min.js` | Bootstrap JS bundle (vendorado — não editar) |
| `static/vendor/bootstrap-icons/bootstrap-icons.min.css` | Bootstrap Icons CSS (vendorado — não editar) |
| `static/vendor/bootstrap-icons/fonts/` | Fontes dos ícones (`.woff2`/`.woff`) referenciadas pelo CSS |
| `static/vendor/jsQR.js` | jsQR 1.4.0 (vendorado — não editar). Carregado **sob demanda** por `static/qr-scan.js` só quando o navegador não tem `BarcodeDetector` (iOS Safari); 250 KB não custam nada nas outras páginas |
| `static/vendor/jsQR.LICENSE.txt` | Texto da Apache-2.0, que exige acompanhar a redistribuição |
| `static/qr-scan.js` | Scanner de QR do botão da navbar (modal `templates/_qr_scan_modal.html`): lê `/spools/<id>` e navega na **mesma aba** para o rolo ou a pesagem (preferência por aparelho em `localStorage` `sc.scanTarget`) |
| `static/vendor/VENDORED.txt` | Carimbo das versões vendoradas (gerado pelo script) |
| `templates/base.html`, `templates/login.html` | Referenciam `static/vendor/...` via `url_for('static', …)` |

## Licença / atribuição

**jsQR 1.4.0 é Apache-2.0** (github.com/cozmo/jsQR; licença em `static/vendor/jsQR.LICENSE.txt`). Bootstrap e Bootstrap Icons são **MIT** (getbootstrap.com / icons.getbootstrap.com). As versões
vendoradas ficam registradas em `static/vendor/VENDORED.txt`.
