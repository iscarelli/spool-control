# Vikunja — usar via MCP, não conexão direta

Este projeto integra com o Vikunja **através do MCP server**, não por chamadas diretas à API.

## Como usar

- Use as **ferramentas do MCP `vikunja`** (criar/listar/atualizar tasks, etc.).
- **Não** chame a API REST diretamente (`curl https://vikunja.lojinharacer.com.br/api/v1/...`) nem cole o token em scripts.

## Configuração

- O MCP server é `@democratize-technology/vikunja-mcp`, declarado em `~/.claude.json` (escopo deste projeto), executado via `npx`.
- `VIKUNJA_URL`: `https://vikunja.lojinharacer.com.br/api/v1`
- `VIKUNJA_API_TOKEN`: **não fica em texto plano**. Vem da variável de ambiente `$VIKUNJA_API_TOKEN`, definida no `~/.zshrc`.
  - No config: `"VIKUNJA_API_TOKEN": "${VIKUNJA_API_TOKEN}"`.

## Se o token parar de funcionar

1. Verifique se a env var está carregada: `echo $VIKUNJA_API_TOKEN`.
2. Se vazio, recarregue o shell (`source ~/.zshrc`) ou abra novo terminal.
3. Para rotacionar: gere novo token no Vikunja e atualize **só** o `~/.zshrc`.

> Movido de texto plano no `~/.claude.json` para `$VIKUNJA_API_TOKEN` em 2026-06-10.
