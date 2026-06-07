/* ── niimbot-spool.js — adaptador do driver Niimbot para o spool-control ──────
 * Cola específica deste app sobre o driver genérico (static/niimbot.js, vendorado
 * de iscarelli/niimbot-web-bluetooth). Aqui mora tudo que é do spool-control: busca
 * o registro em /api/niimbot/registry e liga os botões da UI.
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
  function activeModel(rg) { return rg.models[rg.selected_model] || Object.values(rg.models)[0]; }
  function activeSize(rg) { return rg.sizes[rg.selected_size] || Object.values(rg.sizes)[0]; }

  async function printOne(url, onProgress) {
    const rg = await loadRegistry();
    await Niimbot.printImage(url, { model: activeModel(rg), size: activeSize(rg), onProgress });
  }
  async function printMany(urls, onProgress) {
    const rg = await loadRegistry();
    await Niimbot.printBatch(urls, { model: activeModel(rg), size: activeSize(rg), onProgress });
  }

  function wireButton(btn, run) {
    if (!Niimbot.isSupported()) {
      btn.disabled = true;
      btn.title = "Use Chrome ou Edge em HTTPS para imprimir direto na Niimbot.";
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
        btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Impresso';
        setTimeout(() => { btn.innerHTML = original; btn.disabled = false; }, 2500);
      } catch (err) {
        console.error("[Niimbot]", err);
        const msg = (err && err.name === "NotFoundError")
          ? "Nenhuma impressora selecionada." : (err && err.message) || "Falha na impressão.";
        btn.innerHTML = original; btn.disabled = false;
        alert("Niimbot: " + msg);
      }
    });
  }

  function init() {
    document.querySelectorAll("[data-niimbot-url]").forEach((btn) =>
      wireButton(btn, (status) => printOne(btn.dataset.niimbotUrl, status)));
    document.querySelectorAll("[data-niimbot-urls]").forEach((btn) => {
      let urls = [];
      try { urls = JSON.parse(btn.dataset.niimbotUrls); } catch (e) { /* ignore */ }
      wireButton(btn, (status) => printMany(urls, status));
    });
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
