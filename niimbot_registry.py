"""Registro de modelos de impressora Niimbot e tamanhos de etiqueta.

VENDORADO de iscarelli/niimbot (privado): registry.json. Mantenha em sincronia
com aquele arquivo — o upstream é a fonte de verdade canônica (ver docs/niimbot.md).
Esta é a versão Python (o app importa este módulo); espelha o firmware do projeto
ESP32-Telemetria-Suite (lib/NiimbotBLE/src/NiimbotLabels.h + main_programmer.cpp).
Exposto ao cliente via GET /api/niimbot/registry para o static/niimbot.js.

Para adicionar um modelo ou tamanho novo, basta acrescentar uma entrada aqui —
os dropdowns de configuração e o endpoint de bitmap passam a oferecê-lo
automaticamente. Se o protocolo do novo modelo diferir, adicione também o ramo
correspondente em static/niimbot.js (campo "protocol").
"""

# Modelos de impressora Niimbot. Hoje só a B1 Pro (300 dpi, protocolo V4).
#   density / label_type / speed vêm do firmware (NIM_DENSITY=3, type=1 com
#   gaps, NIM_SPEED=1). name_prefixes filtra o dispositivo BLE pelo nome anunciado.
PRINTER_MODELS = {
    "b1pro": {
        "label": "Niimbot B1 Pro",
        "dpi": 300,
        "protocol": "v4",
        "density": 3,
        "label_type": 1,
        "speed": 1,
        "name_prefixes": ["B1"],
    },
}

# Tamanhos de etiqueta (código Niimbot -> dimensões). Hoje só T50*30.
#   w_px = eixo do printhead (largura), h_px = eixo de avanço (comprimento).
#   Calibrado no firmware: T50*30 = 584 x 354 px @ 300 dpi.
LABEL_SIZES = {
    "T50x30": {
        "label": "50 × 30 mm",
        "code": "T50*30",
        "w_mm": 50,
        "h_mm": 30,
        "w_px": 584,
        "h_px": 354,
        "margin": 10,
    },
}

DEFAULT_MODEL = "b1pro"
DEFAULT_SIZE = "T50x30"


def get_model(key: str) -> dict:
    return PRINTER_MODELS.get(key, PRINTER_MODELS[DEFAULT_MODEL])


def get_size(key: str) -> dict:
    return LABEL_SIZES.get(key, LABEL_SIZES[DEFAULT_SIZE])
