"""Pacote de rotas do spool-control.

Cada módulo aqui agrupa as rotas de um assunto (filaments, spools, admin, …) e
compartilha o MESMO objeto `app` definido em app.py (`from app import app`). Os nomes
das funções/endpoints são idênticos aos de quando tudo morava em app.py, então nenhum
`url_for(...)` de template muda. app.py importa estes módulos no final (evita import
circular) — ver o bloco "Registro das rotas" lá.
"""
