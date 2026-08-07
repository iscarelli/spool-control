# Armadilhas

Código: nenhum — é um índice de pegadinhas do projeto inteiro; cada entrada aponta o
`arquivo:linha` da sua. Uma linha por armadilha, **no mesmo commit do fix**.

🔥 = já cobrou custo (o custo está escrito). Sem marca = confirmada no código, ainda não
mordeu.

---

- 🔥 **`update-lxc.sh` roda da cópia instalada, que ele mesmo atualiza.** Uma mudança no
  script só vale a partir do deploy **seguinte** (`deploy/update-lxc.sh`, passo do
  `git archive`). **Custo:** LXC atualizada com script antigo entra em crash loop por
  módulo faltando; recuperação exige rodar o script direto de um clone, não da cópia
  instalada em `/opt/spool-control/deploy/`.

- 🔥 **Reverter uma feature e reusar o número de versão gera colisão.** A v1.37.0 foi
  publicada, revertida (`c064b61` → `80490e9`) e o **mesmo número** foi reusado para uma
  entrega diferente (`f169c8e`, "excluir rolo + cadastro em lote"), enquanto a feature
  original seguia carimbando `VERSION=1.37.0` fora da `main`. **Custo:** um número
  designou duas entregas diferentes por ~1 mês, e a auditoria de 2026-07-19 teve de
  renumerar. Depois de reverter, **queime o número** — não o recicle.
  **Irmãs — quem mais consome o número da versão:** `app.py` (`APP_VERSION` e
  `current_version()`, que relê do disco), `deploy/update-lxc.sh` (grava o status do
  deploy), `GET /health` (campo `version`) e as tags `vX.Y.Z`. Um número reusado aparece
  errado nos cinco.

- 🔥 **`<form>` dentro de `<form>` não dá erro — o navegador descarta o de dentro.** HTML5
  proíbe form aninhado; o parser joga fora a tag interna e o `<button type="submit">` dela
  passa a pertencer ao form **externo**. O botão então submete a rota errada, e o
  `data-sc-confirm` (lido de `e.target` em `static/spool.js:24`) nunca dispara, porque o
  form que carregava o atributo não existe no DOM. Nada falha visivelmente: o POST retorna
  200 e um flash de sucesso — **do outro form**. **Custo:** "Finalizar Spool" e "Remover
  filamento" nunca funcionaram a partir das telas de edição; o usuário via "Rolo
  atualizado" e o rolo continuava ativo. Corrigido na v1.38.6
  (`templates/spools/form.html`, `templates/filaments/form.html`) tirando o form de ação
  de dentro do form de edição e ligando o botão pelo atributo HTML5 `form="<id>"`.
  **Irmãs — quem mais pode ter o buraco:** qualquer botão de ação (finalizar, remover,
  enfileirar) colocado no rodapé de uma tela de edição. Os dois casos do projeto eram os
  únicos, e `tests/test_nested_form.py` agora falha se aparecer um terceiro. O padrão
  correto está em `templates/spools/list.html:106`, onde o form é irmão, não aninhado.
  **Teste de rota não pega isto** — as rotas sempre estiveram certas; quem quebrava era o
  HTML renderizado.

- **`git describe --tags` é relativo ao HEAD e mente numa branch atrasada.** Numa branch
  que não contém as tags recentes ele devolve uma tag antiga como se fosse a última. Use
  `git tag --sort=-v:refname | head -1`. Confirmado na auditoria de 2026-07-19: `describe`
  devolveu `v1.36.0` com `v1.38.2` já publicada.
  **Irmãs — outras leituras de "última versão" que podem divergir:** o `VERSION` do
  checkout atual, `git show origin/main:VERSION`, e a release resolvida no servidor por
  `update-lxc.sh --latest-release` (que consulta o GitHub, não o clone local).

- **`--preload` no gunicorn é obrigatório.** Sem ele, dois workers correm no bootstrap e
  dá race condition. Ver `deploy/gunicorn.conf.py`.

- **`bi-balance-scale` não existe no Bootstrap Icons 1.11.3.** Usar a classe CSS
  `icon-scale` (`static/icon-scale.svg`). Ícone inexistente some sem erro no console.

- **Botão `disabled` não dispara mouse events**, então tooltip nele não aparece. Envolver
  em `<span data-bs-toggle="tooltip">`.

- **`static/brands/` e `spool.env` não estão no git** — o primeiro é gerado por
  `deploy/seed_brands.py` no servidor, o segundo na instalação. O deploy por
  `git archive` **não os apaga**, mas um clone limpo não os tem.
