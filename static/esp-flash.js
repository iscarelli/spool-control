/* ── esp-flash.js — adaptador do esptool-js para o spool-control ───────────────
 * Cola específica deste app sobre o driver genérico (static/esptool.js, vendorado
 * de esptool-js@0.6.0). Grava o firmware da balança (ESP32-C3) direto do navegador
 * via Web Serial — irmão do gravador Niimbot por Web Bluetooth.
 *
 * Requer secure context (HTTPS ou localhost) e Chrome/Edge desktop (navigator.serial).
 * O binário é o MERGED em 0x0 (static/firmware/balanca-c3.bin), gerado por
 * deploy/build-firmware-bin.sh. As mensagens vêm traduzidas do servidor num
 * <script type="application/json" id="esp-flash-i18n"> renderizado pelo template.
 *
 * Marcação esperada na página:
 *   #esp-flash-btn        botão "Conectar e gravar" (data-fw-url=<bin>)
 *   #esp-flash-progress   <div> da barra (filho .progress-bar opcional)
 *   #esp-flash-log        <pre>/<div> p/ log
 *   #esp-flash-i18n       JSON com as strings traduzidas
 */
import { ESPLoader, Transport } from "./esptool.js";

(function () {
  "use strict";

  const FALLBACK = {
    unsupported: "Use o Chrome ou o Edge no computador (Web Serial).",
    confirm: "Isto vai gravar o firmware na balança conectada. Continuar?",
    connecting: "Conectando…",
    connected: "Conectado: ",
    downloading: "Baixando firmware…",
    flashing: "Gravando…",
    resetting: "Reiniciando a placa…",
    done: "Gravação concluída. A balança vai reiniciar.",
    cancelled: "Cancelado.",
    no_port: "Nenhuma porta selecionada.",
    error: "Falha: ",
  };

  function i18n() {
    const el = document.getElementById("esp-flash-i18n");
    if (!el) return FALLBACK;
    try {
      return Object.assign({}, FALLBACK, JSON.parse(el.textContent || "{}"));
    } catch (_e) {
      return FALLBACK;
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("esp-flash-btn");
    if (!btn) return;
    const t = i18n();
    const logEl = document.getElementById("esp-flash-log");
    const progWrap = document.getElementById("esp-flash-progress");
    const progBar = progWrap ? progWrap.querySelector(".progress-bar") : null;
    const manifestUrl = btn.getAttribute("data-manifest-url");

    function log(msg) {
      if (logEl) {
        logEl.textContent += (logEl.textContent ? "\n" : "") + msg;
        logEl.scrollTop = logEl.scrollHeight;
      }
    }
    function setProgress(pct) {
      if (!progWrap) return;
      progWrap.classList.toggle("d-none", pct == null);
      if (progBar && pct != null) {
        const v = Math.max(0, Math.min(100, Math.round(pct)));
        progBar.style.width = v + "%";
        progBar.textContent = v + "%";
        progBar.setAttribute("aria-valuenow", String(v));
      }
    }

    // Sem Web Serial → desabilita e avisa (não some o botão; explica o porquê).
    if (!("serial" in navigator)) {
      btn.disabled = true;
      log(t.unsupported);
      return;
    }

    btn.addEventListener("click", async function () {
      if (!window.confirm(t.confirm)) return;

      btn.disabled = true;
      if (logEl) logEl.textContent = "";
      setProgress(null);

      let transport = null;
      try {
        // 1) Usuário escolhe a porta serial (gesto obrigatório).
        let port;
        try {
          port = await navigator.serial.requestPort();
        } catch (e) {
          log(t.no_port);
          return; // cancelou o picker — silencioso
        }

        // 2) Conecta e detecta o chip.
        log(t.connecting);
        transport = new Transport(port, false);
        const loader = new ESPLoader({
          transport,
          // Conecta a 115200 e SOBE para 921600 na gravação — exatamente o que o
          // `pio upload` (CLI) faz e que grava 100% de forma estável. Manter os dois
          // iguais faz o esptool-js NÃO trocar de baud (ficava em 115200) e a
          // gravação falhava no bloco final. O baud também ajusta os timeouts internos.
          baudrate: 921600,
          romBaudrate: 115200,
          terminal: {
            clean() {},
            writeLine(d) { log(String(d)); },
            write(d) { /* ruído de bytes crus — ignora */ },
          },
        });
        const chip = await loader.main();
        log(t.connected + (chip || "ESP32-C3"));

        // 3) Baixa o manifesto e os 4 pedaços (mesma origem; sem segredos).
        log(t.downloading);
        const mresp = await fetch(manifestUrl, { cache: "no-store" });
        if (!mresp.ok) throw new Error("HTTP " + mresp.status + " @ " + manifestUrl);
        const manifest = await mresp.json();
        const baseUrl = new URL(".", new URL(manifestUrl, location.href));
        const fileArray = [];
        for (const part of manifest.parts) {
          const url = new URL(part.file, baseUrl).href;
          const r = await fetch(url, { cache: "no-store" });
          if (!r.ok) throw new Error("HTTP " + r.status + " @ " + part.file);
          fileArray.push({
            // Uint8Array (NÃO "binary string"): o esptool-js trata data como bytes
            // (Uint8Array.set, deflate). Passar string faz o pako interpretá-la como
            // UTF-8 e expandir os bytes ≥ 0x80 → o stub infla mais do que o declarado
            // e rejeita o bloco final (ESP_TOO_MUCH_DATA / status 0xC9).
            data: new Uint8Array(await r.arrayBuffer()),
            address: Number(part.offset),   // "0x10000" → 65536
          });
        }

        // 4) Grava os pedaços SEPARADOS, cada um no seu offset — exatamente como o
        //    `pio upload`. Gravar pedaços separados (e não uma imagem merged única
        //    em 0x0) é o que funciona com o esptool-js: na imagem única ele erra o
        //    endereço de bloco e falha no meio ("Failed to write compressed data
        //    after seq N"). Apagamento por-região (eraseAll:false): o esptool-js
        //    calcula a região certa a partir do tamanho de cada arquivo.
        log(t.flashing);
        setProgress(0);
        const sizes = fileArray.map(function (f) { return f.data.length; });
        const totalBytes = sizes.reduce(function (a, b) { return a + b; }, 0);
        await loader.writeFlash({
          fileArray,
          flashSize: "keep",
          flashMode: "keep",
          flashFreq: "keep",
          eraseAll: false,   // apagamento por-região, como o `pio upload`
          compress: true,
          reportProgress(fileIndex, written, _total) {
            let done = written;
            for (let i = 0; i < fileIndex; i++) done += sizes[i];
            setProgress(totalBytes ? (done / totalBytes) * 100 : 0);
          },
        });

        // 5) Reinicia p/ rodar o firmware novo.
        log(t.resetting);
        try { await loader.hardReset(); } catch (_e) { /* alguns C3 resetam sozinhos */ }
        setProgress(100);
        log(t.done);
      } catch (err) {
        log(t.error + (err && err.message ? err.message : String(err)));
      } finally {
        if (transport) { try { await transport.disconnect(); } catch (_e) {} }
        btn.disabled = false;
      }
    });
  });
})();
