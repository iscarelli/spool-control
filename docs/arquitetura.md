# Arquitetura — organização das rotas

Código: app.py, routes/*.py, routes/account.py, routes/passkey.py, static/passkey.js, database.py

Documento de referência sobre **como o código é organizado** e **por que** foi feito
assim. Escrito em termos simples (o mantenedor é iniciante em desenvolvimento).

## O problema

No começo, **todas as rotas** (cada página/URL) viviam num único `app.py` com ~1570
linhas. Funciona, mas fica difícil de achar coisa e arriscado de mexer: qualquer edição
acontece num arquivo gigante.

## As duas formas de resolver

Ambas quebram o arquivo grande em arquivos menores por assunto. A diferença é *como*.

### Analogia
Pense no app como uma **empresa** e cada rota como um **funcionário** com um ramal (a URL).

- **O que adotamos — módulos compartilhando o mesmo `app`:** continua **uma empresa só**;
  só organizamos os funcionários em **salas** (`routes/filaments.py`, `routes/admin.py`…).
  Os ramais (URLs) e os nomes pelos quais um chama o outro **continuam idênticos**.
- **Blueprints (o jeito "oficial" do Flask):** cria **departamentos formais**. Fica mais
  "de livro", mas cada rota passa a ter **nome composto** (`filaments_list` →
  `filamentos.filaments_list`), e **todo** lugar que usa esse nome precisa ser reescrito.

Esse "nome pelo qual um chama o outro" é o **`url_for(...)`** — que aparece **139× nos
templates + ~80× no Python**. Com Blueprints, as ~219 referências teriam que ser revisadas;
com a abordagem adotada, **nenhuma**.

## Comparação

| Critério | Módulos + `app` compartilhado (adotado) | Blueprints (oficial) |
|---|---|---|
| Quebra o arquivo grande | ✅ Sim | ✅ Sim |
| Muda `url_for` nos templates | ✅ Não (0) | ❌ Sim (~219 lugares) |
| Risco num app em produção | 🟢 Baixo | 🟠 Médio/alto |
| URLs mudam para o usuário | 🟢 Não | 🟢 Não |
| Padrão "de mercado" do Flask | ➖ Não é o oficial | ✅ Sim |
| Prefixo de URL automático (ex.: `/admin/*`) | ❌ Não | ✅ Sim |
| Config/middleware isolado por grupo | ❌ Não | ✅ Sim |
| Esforço/risco da migração agora | 🟢 Pequeno | 🟠 Grande |
| Adequação a projeto pequeno/médio | ✅ Ideal | ⚠️ Mais do que precisa |
| Adequação a projeto enorme/multi-times | ⚠️ Aceitável | ✅ Melhor |

## Como funciona na prática

- `app.py` é o **núcleo**: cria o objeto `app`, configura segurança/CSP, logging, helpers
  (`t`, `_safe_next`, `_label_spool`, `public_base_url`…), decorators (`login_required`,
  `admin_required`, `demo_blocked`), `login`/`logout` e os *error handlers*.
- `routes/*.py` agrupam as rotas por assunto. Cada módulo faz
  `from app import app, login_required, …` e registra suas rotas com `@app.route`.
- **No final** do `app.py`, um único `from routes import (...)` importa os módulos. Isso é
  o que "liga" as rotas ao app. Importar no fim (e não no topo) evita *import circular*:
  quando os módulos rodam, tudo que eles precisam do `app.py` já está definido.
- Os **nomes de endpoint continuam iguais** aos de quando tudo morava no `app.py` (as
  funções têm os mesmos nomes), então **nenhum `url_for` muda**.

## Por que essa escolha

O app é **pequeno, em produção e com poucos usuários** — a prioridade nº 1 é **não quebrar
nada**. As duas formas deixam o código igualmente organizado; Blueprints traria muita
mudança arriscada (as ~219 referências) em troca de benefícios que o projeto **ainda não
precisa** (prefixos automáticos, config isolada por grupo). Ficamos com **~90% do ganho
com ~10% do risco**.

Se um dia o projeto crescer muito (vários times, dezenas de áreas), migrar para Blueprints
faz sentido — e dá para fazer **depois**, gradualmente, usando a **suíte de testes**
(`tests/`) como rede de segurança.

> Princípio que guia estas decisões: **use a solução mais simples que resolve o problema de
> hoje; só pague a complexidade extra quando a necessidade dela aparecer de verdade.**

## Login em duas etapas: TOTP e passkey

Código: `app.py` (`login`, `login_2fa`, `_promote_session`), `routes/account.py`
(`account_2fa`), `routes/passkey.py`, `static/passkey.js`, `database.py`
(`webauthn_credentials`, `disable_totp`).

- Senha é sempre o 1º passo. Com 2FA ligado, o app guarda `pre2fa_*` na sessão e manda
  para `/login/2fa`, onde vale **um** de: código TOTP, código de recuperação ou **passkey**
  (Face ID / Touch ID via WebAuthn). Passkey **não** é login sem senha.
- Passkey só pode ser registrada por quem já tem TOTP ligado (`/account/2fa`). Desativar o
  2FA (`database.disable_totp`) e o `deploy/reset-2fa.py` apagam as passkeys — não sobra
  segundo fator órfão.
- O `rp_id` e a origem esperada vêm de **cada requisição** (`routes/passkey.py:_rp`):
  hostname sem porta e `esquema://host`. Atrás do Traefik isso depende do `ProxyFix`
  (`app.py`, `x_host=1, x_proto=1`) para o esquema ser `https`. Uma passkey vale só para o
  domínio onde foi criada: trocar o domínio da instalação invalida as passkeys (o TOTP segue).
- O challenge fica na sessão e é descartado (`pop`) a cada verificação — uso único. A
  verificação de login usa o mesmo throttle por IP do TOTP e registra falha em
  `login_failures`. O `sign_count` é atualizado a cada uso.
- `User verification` é obrigatória nos dois fluxos (biometria/PIN do aparelho).

