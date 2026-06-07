# Arquitetura — organização das rotas

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
