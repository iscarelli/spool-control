// Balança HX711 + OLED SH1106 + WS2812 — ESP32-C3 Super Mini
// Pinagem:
//   HX711  DOUT=2  SCK=3
//   OLED   SDA=4   SCL=5  (SW I2C)
//   WS2812 DIN=6
//
// Serial: 115200. Comandos no modo normal:
//   c  — entra no modo de calibração
//   t  — zera (tare) sem calibrar

#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <HX711.h>
#include <FastLED.h>
#include <Preferences.h>

#define HX711_DOUT  2
#define HX711_SCK   3
#define OLED_SDA    4
#define OLED_SCL    5
#define WS2812_PIN  6
#define NUM_LEDS    1
#define BOOT_BTN    9  // provisório — trocar por botão dedicado

#define CAL_FACTOR_DEFAULT  437.4f

static U8G2_SH1106_128X64_NONAME_F_SW_I2C u8g2(U8G2_R0, OLED_SCL, OLED_SDA, U8X8_PIN_NONE);
static HX711      scale;
static CRGB       leds[NUM_LEDS];
static Preferences prefs;
static float      s_cal;

enum class CalState { None, Tare, EnterWeight, Measure, Confirm };
static CalState   s_state    = CalState::None;
static float      s_known    = 0;
static float      s_newCal   = 0;

// ─── Display helpers ────────────────────────────────────────────────────────

static void dispLines(const char* l1, const char* l2 = "", const char* l3 = "") {
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_profont11_tf);
    if (*l1) u8g2.drawStr(0, 12, l1);
    if (*l2) u8g2.drawStr(0, 26, l2);
    if (*l3) u8g2.drawStr(0, 40, l3);
    u8g2.sendBuffer();
}

static float weightCeiling(float g, float* pct_out) {
    static const float brk[] = {100, 200, 300, 400, 500, 1000, 2000, 3000, 4000, 5000};
    float ceil = 100;
    for (int i = 0; i < 10; i++) {
        if (g <= brk[i]) { ceil = brk[i]; break; }
        ceil = brk[i]; // acima de 5000 mantém 5000
    }
    if (pct_out) *pct_out = (g <= 0 ? 0 : g / ceil * 100.0f);
    return ceil;
}

static void dispWeight(float g) {
    float pct, ceil;
    ceil = weightCeiling(g < 0 ? 0 : g, &pct);
    if (pct > 100) pct = 100;

    int barFill = (int)(pct / 100.0f * 124);
    if (barFill < 0)   barFill = 0;
    if (barFill > 124) barFill = 124;

    char weightBuf[16], rightBuf[20];
    snprintf(weightBuf, sizeof(weightBuf), "%.1f g", g);
    snprintf(rightBuf,  sizeof(rightBuf),  "%d%% - %.0fg", (int)pct, ceil);

    u8g2.clearBuffer();

    // Linha de topo: "Peso:" esquerda, "XX% /YYYg" direita
    u8g2.setFont(u8g2_font_profont11_tf);
    u8g2.drawStr(0, 10, "Peso:");
    u8g2.drawStr(128 - u8g2.getStrWidth(rightBuf), 10, rightBuf);

    // Valor do peso centralizado, fonte grande
    u8g2.setFont(u8g2_font_profont22_tf);
    int wx = (128 - (int)u8g2.getStrWidth(weightBuf)) / 2;
    u8g2.drawStr(wx < 0 ? 0 : wx, 42, weightBuf);

    // Barra de progresso
    u8g2.drawFrame(0, 50, 128, 12);
    if (barFill > 0)
        u8g2.drawBox(1, 51, barFill, 10);

    u8g2.sendBuffer();
}

static void setLed(CRGB color) {
    leds[0] = color;
    FastLED.show();
}

// ─── Calibração ─────────────────────────────────────────────────────────────

static void saveCal(float f) {
    s_cal = f;
    scale.set_scale(s_cal);
    prefs.begin("balanca", false);
    prefs.putFloat("cal", s_cal);
    prefs.end();
}

static void calPrompt(const char* serial_msg, const char* d1, const char* d2 = "", const char* d3 = "") {
    Serial.println(serial_msg);
    dispLines(d1, d2, d3);
}

static void startCal() {
    s_state = CalState::Tare;
    setLed(CRGB::Blue);
    Serial.println();
    Serial.println("=== CALIBRACAO ===");
    calPrompt("Passo 1: retire tudo da balanca e pressione Enter.",
              "CAL 1/3", "Retire o peso", "e aperte Enter");
}

static void stepTare() {
    scale.tare();
    s_state = CalState::EnterWeight;
    calPrompt("Zerado.\nPasso 2: digite o peso conhecido (g) e pressione Enter.",
              "CAL 2/3", "Digite o peso", "em gramas + Enter");
}

static void stepEnterWeight(const String& input) {
    float w = input.toFloat();
    if (w <= 0) {
        Serial.println("Valor invalido. Digite novamente:");
        return;
    }
    s_known = w;
    s_state = CalState::Measure;
    char msg[40];
    snprintf(msg, sizeof(msg), "Peso: %.1f g", s_known);
    Serial.println(msg);
    calPrompt("Passo 3: coloque o peso na balanca e pressione Enter.",
              "CAL 3/3", "Coloque o peso", "e aperte Enter");
}

static void stepMeasure() {
    float raw = scale.get_value(10);
    s_newCal  = raw / s_known;

    scale.set_scale(s_newCal);
    float check = scale.get_units(5);

    char line1[32], line2[32];
    snprintf(line1, sizeof(line1), "Fator: %.2f", s_newCal);
    snprintf(line2, sizeof(line2), "Lido: %.1f g", check);

    Serial.println(line1);
    Serial.printf("Verificacao: %.1f g (esperado %.1f g)\r\n", check, s_known);
    Serial.println("'s' para salvar  'r' para repetir  'x' para cancelar");

    dispLines("CAL resultado", line1, line2);
    s_state = CalState::Confirm;
}

static void stepConfirm(const String& input) {
    char cmd = input.length() > 0 ? tolower(input[0]) : 0;
    if (cmd == 's') {
        saveCal(s_newCal);
        Serial.printf("Salvo! Fator: %.2f\r\n", s_cal);
        s_state = CalState::None;
        setLed(CRGB::Green);
        dispLines("Calibrado!", "");
        delay(800);
    } else if (cmd == 'r') {
        s_state = CalState::Measure;
        scale.set_scale(s_cal); // reverte temporario para medir novamente
        calPrompt("Repetindo. Certifique-se que o peso esta na balanca e pressione Enter.",
                  "CAL 3/3", "Coloque o peso", "e aperte Enter");
    } else if (cmd == 'x') {
        scale.set_scale(s_cal); // descarta
        s_state = CalState::None;
        setLed(CRGB::Green);
        Serial.println("Cancelado.");
        dispLines("Cancelado");
        delay(500);
    } else {
        Serial.println("'s' salvar  'r' repetir  'x' cancelar");
    }
}

static void handleSerial(const String& input) {
    switch (s_state) {
        case CalState::None:
            if (input == "c") { startCal(); return; }
            if (input == "t") { scale.tare(); Serial.println("Zerado."); return; }
            break;
        case CalState::Tare:       stepTare();             break;
        case CalState::EnterWeight: stepEnterWeight(input); break;
        case CalState::Measure:    stepMeasure();           break;
        case CalState::Confirm:    stepConfirm(input);      break;
    }
}

// ─── Setup / Loop ───────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);

    FastLED.addLeds<WS2812, WS2812_PIN, GRB>(leds, NUM_LEDS);
    FastLED.setBrightness(40);
    setLed(CRGB::Yellow);

    u8g2.begin();
    dispLines("Iniciando...");

    prefs.begin("balanca", true);
    s_cal = prefs.getFloat("cal", CAL_FACTOR_DEFAULT);
    prefs.end();
    Serial.printf("Fator de calibracao: %.2f\r\n", s_cal);

    pinMode(BOOT_BTN, INPUT_PULLUP);

    scale.begin(HX711_DOUT, HX711_SCK);
    scale.set_scale(s_cal);
    dispLines("Zerando...");
    scale.tare();

    setLed(CRGB::Green);
    dispLines("Pronto", "'c' calibrar  't' zerar");
    Serial.println("Pronto. 'c' calibrar | 't' zerar");
    delay(500);
}

void loop() {
    // Leitura serial linha a linha
    static String inputBuf;
    while (Serial.available()) {
        char ch = Serial.read();
        if (ch == '\n' || ch == '\r') {
            Serial.print("\r\n");
            inputBuf.trim();
            if (inputBuf.length() > 0 || s_state != CalState::None)
                handleSerial(inputBuf);
            inputBuf = "";
        } else {
            Serial.print(ch); // echo
            inputBuf += ch;
        }
    }

    if (s_state != CalState::None) return; // não atualiza peso durante calibração

    static uint32_t lastRead    = 0;
    static uint32_t lastPrint   = 0;
    static uint32_t lastHint    = 0;
    static bool     ledOn       = true;
    static float    filtered    = 0;
    static bool     fInit       = false;
    static bool     btnLast     = HIGH;
    static uint32_t btnDebounce = 0;

    uint32_t now = millis();

    // Botão BOOT — provisório
    bool btnNow = digitalRead(BOOT_BTN);
    if (btnLast == HIGH && btnNow == LOW && now - btnDebounce > 50) {
        btnDebounce = now;
        scale.tare();
        fInit = false;
        Serial.print("Zerado (botao).\r\n");
    }
    btnLast = btnNow;

    if (now - lastHint >= 10000) {
        lastHint = now;
        Serial.print("  'c' calibrar | 't' zerar\r\n");
    }

    // Lê a cada ~120ms (get_units(1) = 1 amostra HX711 ≈ 100ms)
    if (now - lastRead < 120) return;
    lastRead = now;
    if (!scale.is_ready()) return;

    float raw = scale.get_units(1);

    // Filtro adaptativo: salta se mudança > 15g, suaviza se estável
    if (!fInit || fabsf(raw - filtered) > 15.0f) {
        filtered = raw;
        fInit    = true;
    } else {
        filtered = 0.4f * raw + 0.6f * filtered;
    }

    float display = fabsf(filtered) < 0.3f ? 0.0f : filtered;
    dispWeight(display);

    // Serial e LED a cada 500ms para não spammar
    if (now - lastPrint >= 500) {
        lastPrint = now;
        Serial.printf("%.2f g\r\n", display);
        setLed(ledOn ? CRGB::Green : CRGB::Black);
        ledOn = !ledOn;
    }
}
