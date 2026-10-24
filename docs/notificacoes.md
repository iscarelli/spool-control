Código: notify.py, push.py, deploy/backup-cron.py, translations.py, tests/test_notification_triggers.py,
routes/notifications.py, templates/account/notifications.html,
static/notifications.js, static/sw.js, database.py (tabelas `push_subscriptions`, `low_stock_notified` e
`notification_prefs` + helpers), requirements.txt (pywebpush e transitivas),
LXC 117:/opt/spool-control/data/vapid.json

# Notificações push

Infraestrutura de Web Push, a página `/account/notifications` e as preferências por usuário.
Os gatilhos (quem dispara cada aviso) estão em `notify.py` e na seção "Gatilhos" abaixo.

## Chaves VAPID

- Geradas **sozinhas** na primeira vez que são necessárias (`push.py:vapid_keys`) — sem passo de
  console, como exige o modelo de várias instalações atualizadas só pela web.
- Guardadas em `data/vapid.json` (`{"private", "public"}`, base64url: escalar de 32 bytes e ponto
  P-256 não comprimido de 65 bytes), escrito de forma atômica com modo 0600. Duas gunicorn workers
  concorrentes: o arquivo temporário é ligado ao nome final com `os.link`, que falha se a outra
  worker chegou antes — vale o par de quem ganhou.
- **Fora do banco, de propósito:** o zip de `/admin/backup` leva `spool.db` e `static/brands/`,
  então as chaves **não** vão no backup. Depois de um restore numa instalação nova, as chaves são
  geradas de novo e os usuários **reativam as notificações** em cada aparelho (as inscrições
  restauradas pertencem às chaves antigas e passam a dar 403/410, sendo apagadas no primeiro envio).
- A chave privada nunca é logada nem devolvida; só a pública sai (a página precisa dela).
- `sub` do VAPID: a URL pública da instalação (`public_base_url()`, `app.py`), **sem barra final**
  (o `py_vapid` recusa `https://host/`); se não for https, cai em `mailto:admin@<host>`.

## Inscrições

- Tabela `push_subscriptions` (id, user_id, endpoint UNIQUE, p256dh, auth, user_agent, created_at,
  last_ok_at). Um aparelho = uma linha. `ON DELETE CASCADE` com o usuário.
- O endpoint vem do cliente e vira um POST do servidor: só são aceitos os serviços de push dos
  navegadores (`push.py:PUSH_HOSTS` / `PUSH_SUFFIXES`: FCM, Apple, Mozilla, Windows), sempre https,
  porta 443, sem IP nem credenciais (guarda anti-SSRF).
- Toda rota age só nas linhas do usuário logado; remover aparelho de outro usuário não faz nada.

## Envio

- `push.send_to_user(user_id, title, body, url)` manda a todos os aparelhos do usuário
  (timeout 10 s). 404/410 apagam a inscrição; qualquer outra falha só vai para o log
  (`push.send_failed`, sem corpo de resposta nem chave).
- `push.send_async(...)` roda isso numa thread daemon: uma requisição (ex.: pesagem) nunca espera
  o serviço de push.
- `pywebpush.webpush` é buscado no módulo na hora da chamada, para os testes trocarem por um fake.

## Preferências

Tabela `notification_prefs` (uma linha por usuário, criada ao salvar; sem linha valem os padrões):
`low_stock_on`/`low_stock_g` (padrão = setting `low_stock_threshold_g`, 200), `last_spool_on`,
`weigh_reminder_on`/`weigh_reminder_days` (padrão 7) e `weigh_reminder_last_at` (carimbo do último lembrete enviado). **Tudo desligado** até o usuário ligar. Gramas 1–5000, dias 1–60; valor inválido
recusa o formulário inteiro. Usuário sem permissão de escrita (`WRITE_ROLES`) não vê nem consegue
ligar o lembrete de pesagem (o servidor força desligado).

## Gatilhos (`notify.py`)

Não importa Flask nem `app.py` (o cron usa). Nada dispara no modo demo (`DEMO_MODE=1`). O usuário
não tem idioma gravado, então os textos saem em português (`notify._tr(lang)` já aceita o idioma;
as traduções EN/ES existem em `translations.py`). Cada gatilho engole o próprio erro: aviso nunca
quebra pesagem nem finalização. Pelas requisições, o envio é `push.send_async`.

- **Rolo acabando** (`low_stock_on`, `low_stock_g`): `notify.after_weighing`, chamado no fim de
  `database.add_weight_reading` — o único `INSERT` em `weight_readings`, então passa por ele a
  pesagem do formulário, a do scanner (`weigh.json`), a de `/weigh`, a API da balança
  (`/api/weigh`) e qualquer caminho futuro (um teste vigia isso). Compara o restante do rolo
  (`current_net_g`, o mesmo número da página do rolo) com o N de cada usuário. Um aviso por
  cruzamento: a tabela `low_stock_notified (user_id, spool_id)` guarda quem já foi avisado; a marca
  sai quando uma pesagem volta a ficar >= N. A primeira pesagem já abaixo de N conta como cruzamento.
  Só rolos ativos. A marca é gravada com `INSERT OR IGNORE`, então duas workers não duplicam o aviso.
  Texto: "Rolo acabando" / "<filamento> (SP-0001): 150 g restantes", abre `/spools/<id>`.
- **Último rolo** (`last_spool_on`): `notify.after_finish`, chamado no fim de
  `database.deactivate_spool` (usado pelo botão do rolo e pelo "finalizar em lote"; não há outro
  caminho de finalização, nem automático). Se sobrou exatamente 1 rolo ativo do mesmo filamento,
  avisa todo usuário com a opção ligada ("Último rolo" / "Só resta 1 rolo de <filamento>", abre
  `/filaments/<id>`). Com 0 ou 2+ restantes, nada. Apagar um rolo não conta como finalizar.
- **Lembrete de pesagem** (`weigh_reminder_*`): `notify.run_weigh_reminders`, terceiro passo
  independente (try/except próprio, e o `import notify` dentro dele) do tick horário
  `deploy/backup-cron.py`. Só entre 09:00 e 21:00 no horário local do servidor; só usuário com
  `WRITE_ROLES`, a opção ligada e pelo menos um aparelho inscrito; só se passaram N dias desde
  `weigh_reminder_last_at` (ou nunca enviou) E há rolos ativos sem pesagem há mais de N dias (ou
  nunca pesados). Sem rolo atrasado não faz nada e **não** avança o carimbo. Envio síncrono
  (`push.send_to_user`). Texto: "Hora de pesar" / "<k> rolos sem pesagem há mais de <N> dias",
  abre `/spools`. `notify.WRITE_ROLES` repete `app.WRITE_ROLES` (um teste exige que sejam iguais).
- O cron manda sem importar `app`: `push.vapid_sub` aplica a mesma regra de `app.public_base_url`
  lendo a setting `app_base_url` e `APP_BASE_URL`.

## Página e permissões do celular

- Menu da conta (`base.html`), ao lado do 2FA. Bloqueada no modo demo como as outras ações de conta.
- "Este aparelho": ativar/desativar neste navegador, lista de aparelhos com remover, "Enviar teste".
- "Permissões do celular": linhas de câmera e notificações. Estado pela Permissions API quando
  existe; senão "Toque em Testar". "Testar" faz o pedido de verdade (câmera: `getUserMedia` traseira,
  trilhas paradas na hora). Negada: mostra o caminho para liberar conforme o aparelho (iPhone com
  app instalado: Ajustes › Spool; iPhone no Safari: Ajustes › Safari; demais: cadeado do endereço).
- Todo o JS está em `static/notifications.js` (CSP com nonce, sem handler inline); os textos chegam
  por `data-i18n`.

## iPhone

Push só funciona com o app **adicionado à Tela de Início** (iOS 16.4 ou mais novo); no Safari comum
o `PushManager` nem existe. A página mostra o passo a passo quando não está em modo standalone.

## Service worker

`static/sw.js` ganhou `push` (payload ilegível ainda mostra uma notificação genérica, senão alguns
navegadores revogam a inscrição) e `notificationclick` (só segue URL da mesma origem). O `fetch`
continua só repassando GET.

## Dependência

`pywebpush==2.5.0` e `py-vapid==1.9.6` com todas as transitivas fixadas em `requirements.txt`
(`aiohttp` e afins vêm só porque o `pywebpush` os importa; o app não usa o envio assíncrono).
O `deploy/update-lxc.sh` instala o `requirements.txt` antes do smoke `import app`, então a dep nova
chega sozinha no update pela web.

Testes: `tests/test_push.py` e `tests/test_notification_triggers.py`.
