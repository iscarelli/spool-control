SUPPORTED = ("pt", "en")

_EN = {
    # Nav
    "Filamentos":         "Filaments",
    "Spools":             "Spools",
    "Carretéis":          "Empty Spools",
    "Carretéis Vazios":   "Empty Spools",
    "Pesar":              "Weigh",
    "Relatórios":         "Reports",
    "Por Material":       "By Material",
    "Por Local":          "By Location",
    "Estoque Baixo":      "Low Stock",
    "Histórico de Peso":  "Weight History",
    "Fila de Etiquetas":  "Label Queue",
    "Admin":              "Admin",
    "Usuários":           "Users",
    "Marcas / Logos":     "Brands / Logos",
    "Configurações":      "Settings",
    "Buscar...":          "Search...",
    "Sair":               "Logout",
    "Tema":               "Theme",

    # Lists — headers
    "Material":           "Material",
    "Marca":              "Brand",
    "Família":            "Family",
    "Spools Ativos":      "Active Spools",
    "Total":              "Total",
    "Local":              "Location",
    "Peso Atual":         "Current Weight",
    "Status":             "Status",
    "Nominal":            "Nominal",
    "Marca / Família":    "Brand / Family",

    # Filaments list
    "Filtrar...":                    "Filter...",
    "+ Novo Filamento":              "+ New Filament",
    "Nenhum filamento cadastrado":   "No filaments registered",
    "Duplicar filamento":            "Duplicate filament",
    "Remover filamento":             "Delete filament",

    # Spools list
    "todos":                "all",
    "Ver finalizados":      "View finished",
    "Só ativos":            "Active only",
    "Fila: Todos":          "Queue: All",
    "+ Novo Spool":         "+ New Spool",
    "Nenhum spool encontrado": "No spools found",

    # Filament detail
    "Diâmetro":                  "Diameter",
    "Notas":                     "Notes",
    "Carretel Vazio":            "Empty Spool",
    "Nenhum spool cadastrado":   "No spools registered",
    "Ativo":                     "Active",
    "Finalizado":                "Finished",

    # Buttons
    "Ver":       "View",
    "Editar":    "Edit",
    "Salvar":    "Save",
    "Cancelar":  "Cancel",
    "Registrar": "Register",
    "Finalizar Spool": "Finish Spool",

    # Weigh modal
    "Peso bruto (g)":               "Gross weight (g)",
    "Erro de rede. Tente novamente.": "Network error. Please try again.",
    "% disponível":                 "% available",
    "% de estoque disponível":      "% stock available",

    # Tooltips / misc
    "Adicionar à fila":  "Add to queue",
    "Remover da fila":   "Remove from queue",

    # Reports
    "Relatório por Material":  "Report by Material",
    "Relatório por Local":     "Report by Location",
    "Histórico":               "History",
}


def get_translator(lang: str):
    table = _EN if lang == "en" else {}

    def _(s: str) -> str:
        return table.get(s, s)

    return _
