/* ── niimbot-spool.js — adaptador do driver Niimbot para o spool-control ──────
 * Cola específica deste app sobre o driver genérico (static/niimbot.js, vendorado
 * de iscarelli/niimbot-web-bluetooth). Aqui mora tudo que é do spool-control: busca
 * o registro em /api/niimbot/registry e liga os botões da UI.
 *
 * Auto-adaptação por impressora: a etiqueta física é a mesma (50×30 mm) na B1 e na
 * B1 Pro — só muda o DPI. O usuário escolhe só o tamanho físico; aqui identificamos
 * a impressora na conexão (Niimbot.identify) e resolvemos internamente o MODELO
 * (por id/task) e a VARIANTE de pixel (mesmo tamanho físico, DPI da impressora),
 * pedindo o PNG na resolução certa. As mensagens vêm traduzidas do servidor (campo
 * `i18n` do registro) — o driver vendorado é só em inglês.
 *
 * Botões:
 *   [data-niimbot-url="/spools/<id>/label.png"]  → imprime 1 etiqueta
 *   [data-niimbot-urls='["/spools/1/label.png", …]'] → imprime a fila em sequência
 */
(function () {
  "use strict";

  let registry = null;
  async function loadRegistry() {
    if (registry) return registry;
    const resp = await fetch("/api/niimbot/registry");
    if (!resp.ok) throw new Error("Falha ao carregar registro Niimbot");
    registry = await resp.json();
    return registry;
  }

  // ── i18n ────────────────────────────────────────────────────────────────────
  // Fallback em PT caso o registro não carregue (idioma da sessão vem do servidor).
  const I18N_FALLBACK = {
    identifying: "identificando impressora…",
    printing: "imprimindo…",
    printed: "Impresso",
    no_printer: "Nenhuma impressora selecionada.",
    failed: "Falha na impressão.",
    unsupported: "Use Chrome ou Edge em HTTPS para imprimir direto na Niimbot.",
    unrecognized: "Impressora não reconhecida ({printer}). Atualize o app ou reporte.",
  };
  function msg(rg, key) { return (rg && rg.i18n && rg.i18n[key]) || I18N_FALLBACK[key] || key; }
  function fmt(tpl, vars) {
    return String(tpl).replace(/\{(\w+)\}/g, (_, k) => (k in vars ? vars[k] : "{" + k + "}"));
  }

  // ── Resolução modelo/tamanho a partir da impressora detectada ────────────────
  // O usuário escolhe a FAMÍLIA (ex.: "Niimbot B1 / B1 Pro"); a detecção decide o
  // modelo exato (e o DPI) dentro dela.
  function selectedFamily(rg) {
    return (rg.families && (rg.families[rg.selected_family] || Object.values(rg.families)[0])) || null;
  }
  // Filtro BLE de descoberta: prefixos da família escolhida (escopo o seletor de
  // dispositivos); sem família, cai na união de todos os prefixos conhecidos.
  function discoveryModel(rg) {
    const fam = selectedFamily(rg);
    const prefixes = (fam && fam.name_prefixes) || [];
    if (prefixes.length) return { name_prefixes: prefixes };
    const set = new Set();
    Object.values(rg.models || {}).forEach((m) => (m.name_prefixes || []).forEach((p) => set.add(p)));
    return { name_prefixes: [...set] };
  }
  // Chave do modelo: SÓ por `model id` confirmado contra os modelos validados — é a
  // identificação confiável (4096/4097/4608). Sem casar um id validado, devolve null e
  // a impressão é recusada (não imprime "no chute" numa Niimbot não suportada).
  function resolveModelKey(rg, info) {
    const fam = selectedFamily(rg);
    const members = (fam && fam.models) || Object.keys(rg.models);
    if (info && info.modelId != null) {
      for (const k of members) if (rg.models[k] && rg.models[k].id === info.modelId) return k;
    }
    return null;
  }
  // Variante de tamanho: mesmo tamanho FÍSICO (mm) do selecionado, cuja "dona" é o
  // modelo resolvido — desambigua B1 Pro vs M2-H (ambos 300 dpi, larguras 584 vs 567).
  // Fallback por DPI da impressora e, por fim, o representante selecionado.
  function resolveSize(rg, info, modelKey) {
    const sm = rg.size_model || {};
    const sel = rg.sizes[rg.selected_size]
      || rg.sizes[(rg.physical_sizes && Object.keys(rg.physical_sizes)[0])]
      || Object.values(rg.sizes)[0];
    for (const k in rg.sizes) {
      const s = rg.sizes[k];
      if (s.w_mm === sel.w_mm && s.h_mm === sel.h_mm && sm[k] === modelKey) return { key: k, size: s };
    }
    if (info && info.dpi != null) {
      for (const k in rg.sizes) {
        const s = rg.sizes[k];
        if (s.w_mm === sel.w_mm && s.h_mm === sel.h_mm && s.dpi === info.dpi) return { key: k, size: s };
      }
    }
    return { key: rg.selected_size, size: sel };
  }
  function withSize(url, key) {
    return url + (url.indexOf("?") >= 0 ? "&" : "?") + "size=" + encodeURIComponent(key);
  }

  // Identifica a impressora e resolve modelo + variante de tamanho. Só prossegue se o
  // `model id` for de um modelo VALIDADO; caso contrário recusa com aviso localizado
  // (evita imprimir errado numa Niimbot não suportada/não identificada).
  async function prepare(rg, onProgress) {
    onProgress && onProgress(msg(rg, "identifying"));
    const info = await Niimbot.identify(discoveryModel(rg));
    const modelKey = resolveModelKey(rg, info);
    if (!modelKey) {
      const who = (info && (info.deviceName
        || (info.modelId != null ? "id " + info.modelId : null))) || "?";
      throw new Error(fmt(msg(rg, "unrecognized"), { printer: who }));
    }
    const model = rg.models[modelKey];
    const sized = resolveSize(rg, info, modelKey);
    return { model, size: sized.size, sizeKey: sized.key };
  }

  async function printOne(url, onProgress) {
    const rg = await loadRegistry();
    const { model, size, sizeKey } = await prepare(rg, onProgress);
    onProgress && onProgress(msg(rg, "printing"));
    await Niimbot.printImage(withSize(url, sizeKey), { model, size });
  }
  async function printMany(urls, onProgress) {
    const rg = await loadRegistry();
    const { model, size, sizeKey } = await prepare(rg, onProgress);
    onProgress && onProgress(msg(rg, "printing"));
    await Niimbot.printBatch(urls.map((u) => withSize(u, sizeKey)), { model, size });
  }

  function wireButton(btn, run, rg) {
    if (!Niimbot.isSupported()) {
      btn.disabled = true;
      btn.title = msg(rg, "unsupported");
      return;
    }
    const original = btn.innerHTML;
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      btn.disabled = true;
      const status = (s) => { btn.innerHTML =
        `<span class="spinner-border spinner-border-sm me-1"></span>${s}`; };
      try {
        await run(status);
        btn.innerHTML = `<i class="bi bi-check-lg me-1"></i>${msg(rg, "printed")}`;
        setTimeout(() => { btn.innerHTML = original; btn.disabled = false; }, 2500);
      } catch (err) {
        console.error("[Niimbot]", err);
        const m = (err && err.name === "NotFoundError")
          ? msg(rg, "no_printer") : (err && err.message) || msg(rg, "failed");
        btn.innerHTML = original; btn.disabled = false;
        alert("Niimbot: " + m);
      }
    });
  }

  async function init() {
    // Carrega o registro antes de ligar os botões (i18n p/ títulos e mensagens).
    let rg = null;
    try { rg = await loadRegistry(); } catch (e) { /* segue com fallback PT */ }
    document.querySelectorAll("[data-niimbot-url]").forEach((btn) =>
      wireButton(btn, (status) => printOne(btn.dataset.niimbotUrl, status), rg));
    document.querySelectorAll("[data-niimbot-urls]").forEach((btn) => {
      let urls = [];
      try { urls = JSON.parse(btn.dataset.niimbotUrls); } catch (e) { /* ignore */ }
      wireButton(btn, (status) => printMany(urls, status), rg);
    });
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
