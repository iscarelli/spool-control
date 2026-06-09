#!/usr/bin/env python3
"""
reset-2fa.py — Desativa a verificação em duas etapas (2FA) de um usuário.

Válvula de escape para LOCKOUT: se o admin perder o app autenticador E os códigos
de recuperação, quem tem acesso ao servidor (usuário `spool` no LXC) roda isto para
zerar o 2FA da conta. O acesso ao servidor é, por design, o fator de recuperação
final desta aplicação self-hosted.

Uso:
    python3 deploy/reset-2fa.py <usuario>

O caminho do banco vem de SPOOL_DB_PATH (mesma var do app); cai no default da
instalação se não definida.
"""
import os
import sys
import sqlite3

DB_PATH = (os.environ.get("SPOOL_DB_PATH")
           or os.environ.get("DB_PATH")
           or "/opt/spool-control/data/spool.db")


def main():
    if len(sys.argv) != 2:
        print(f"Uso: {sys.argv[0]} <usuario>", file=sys.stderr)
        return 2
    username = sys.argv[1]

    if not os.path.exists(DB_PATH):
        print(f"Banco não encontrado: {DB_PATH}", file=sys.stderr)
        print("Defina SPOOL_DB_PATH se o banco estiver em outro caminho.", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        row = conn.execute(
            "SELECT id, totp_enabled FROM users WHERE username=?", (username,)
        ).fetchone()
        if row is None:
            print(f"Usuário não encontrado: {username!r}", file=sys.stderr)
            return 1
        user_id, enabled = row
        conn.execute(
            "UPDATE users SET totp_secret='', totp_enabled=0 WHERE id=?", (user_id,)
        )
        conn.execute("DELETE FROM recovery_codes WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()

    if enabled:
        print(f"2FA desativado para {username!r}. Faça login só com a senha e reative em Conta → Verificação em duas etapas.")
    else:
        print(f"{username!r} já estava sem 2FA — nada a fazer (códigos de recuperação limpos por garantia).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
