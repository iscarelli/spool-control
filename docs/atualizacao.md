# Operação — autoatualização (validação e troubleshooting)

Como funciona o mecanismo de atualização (desde **v1.26.0**) e como **validar** no console
do LXC. Comandos rodados como **root** dentro da LXC (ex.: VMID 117).

## Como funciona (resumo)

1. O admin clica **Atualizar** em `/admin/update` (ou roda `update` no console).
2. O app (usuário `spool`, **não-root**) apenas **escreve** o flag
   `/opt/spool-control/data/.update-requested`. Não usa `sudo`.
3. Um observador `systemd .path` (root, inotify) detecta o flag e dispara o oneshot
   `spool-update.service` — **instantâneo**.
4. O oneshot apaga o flag (`ExecStartPre`, re-armando o observador) e roda
   `update-lxc.sh --latest-release`: clona a última release → **smoke test** (`import app`)
   → aplica a árvore (`git archive`) → reinstala o aparato → **reinicia** o `spool-control`.
5. Se o smoke test falhar, o deploy **aborta** e mantém a versão atual no ar.

> Compat. Proxmox Helper Scripts: no console, o comando **`update`**
> (`/usr/local/bin/update` → `deploy/update-cli.sh`) roda o mesmo fluxo. Root no próprio
> shell é normal/seguro — não é o caminho web.

## Validar a atualização (console root)

### Parte 1 — atualizar e assistir

```bash
journalctl -u spool-update -f -n 0          # terminal 1: acompanha ao vivo
systemctl start spool-update.service        # terminal 2: dispara (ou clique Atualizar na web)
```
Esperado no journal: `Resolvendo ultima release` → `Smoke test OK — aplicando` →
`Configurando autoatualizacao (flag-file + systemd .path)` → `Reiniciando servico` →
`Deploy concluido.`

```bash
cat /opt/spool-control/VERSION              # deve mostrar a versão nova
systemctl is-active spool-control           # active
```

### Parte 2 — confirmar a blindagem (mecanismo sem `sudo`)

```bash
systemctl is-enabled spool-update.path                  # enabled
systemctl status  spool-update.path --no-pager | head   # active (waiting); Triggers: spool-update.service
ls -l /usr/local/bin/update                             # -> /opt/spool-control/deploy/update-cli.sh
test -f /etc/sudoers.d/spool-update && echo "AINDA EXISTE (ruim)" || echo "sudoers removido (OK)"
```
Esperado: `.path` **enabled / active (waiting)**, `update` symlink presente, **sudoers removido**.

### Parte 3 — testar o caminho novo de ponta a ponta (flag → vigia → update)

Simula o que o botão web faz (o app escreve o flag como usuário `spool`):

```bash
journalctl -u spool-update -f -n 0                                   # acompanha
runuser -u spool -- touch /opt/spool-control/data/.update-requested  # dispara via flag
```
O `.path` deve disparar o oneshot na hora. Depois, confirme que o flag foi consumido:

```bash
ls /opt/spool-control/data/.update-requested 2>/dev/null && echo "flag ainda lá (erro)" || echo "flag consumido (OK)"
```

E o comando de console:

```bash
update      # atualiza para a última release publicada
```

## Rollback (se um update quebrar)

```bash
bash /opt/spool-control/deploy/update-lxc.sh --ref v1.26.0   # volta para uma tag anterior
```
(O smoke test já evita subir código que não importa; o serviço atual fica no ar se o novo falhar.)

## Migração entre versões (nuance)

O `update-lxc.sh` **em execução** é o já instalado; os passos novos dele só rodam na
atualização **seguinte** à que os trouxe. Logo:

- **Instalação nova** direto numa versão ≥ 1.26.0: já nasce blindada (o script novo roda de primeira).
- **De 1.26.0 → 1.26.1+**: a atualização **finaliza** a blindagem (instala `.path` + `update`, remove sudoers).
- **De uma versão < 1.26.0 direto para ≥ 1.26.1**: funciona normalmente (o botão usa um
  *fallback* transitório), mas a blindagem total se completa na **próxima** atualização —
  tudo automático, **sem console**.

Em qualquer caso o botão "Atualizar" continua funcionando: nunca há um estado sem o vigia
`.path` **e** sem o grant `sudoers` ao mesmo tempo.
