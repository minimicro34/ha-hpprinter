/* HP Printer dashboard card — bundled with the integration. */
class HPPrinterCard extends HTMLElement {
  static getStubConfig() { return { type: "custom:hpprinter-card" }; }
  static getConfigElement() { return document.createElement("hpprinter-card-editor"); }
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) {
    this._hass = hass;
    if (!this._registry && !this._loading) {
      this._loading = true;
      hass.callWS({ type: "config/entity_registry/list" })
        .then((items) => { this._registry = items.filter((e) => e.platform === "hpprinter"); this._render(); })
        .catch(() => { this._registry = []; this._render(); })
        .finally(() => { this._loading = false; });
    }
    this._render();
  }
  getCardSize() { return 5; }
  _render() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const entries = this._registry || [];
    const ids = [...new Set(entries.map((e) => e.config_entry_id).filter(Boolean))];
    const entryId = this._config.entry_id || ids[0];
    const available = entries.filter((e) => e.config_entry_id === entryId);
    const find = (device, key, domain = "sensor") => {
      const suffix = `_${device}_${domain}_${key}`;
      const row = available.find((e) => e.entity_id.startsWith(domain + ".") && e.unique_id?.endsWith(suffix));
      return row ? this._hass.states[row.entity_id] : null;
    };
    const value = (device, key) => {
      const state = find(device, key);
      return state && !["unknown", "unavailable"].includes(state.state) ? state.state : "—";
    };
    const status = value("main", "device_status") !== "—" ? value("main", "device_status") : value("status", "device_status");
    const printers = [
      ["Impressions", value("printer", "total_impressions")],
      ["Copies", value("copy", "total_impressions")],
      ["Scans", value("scanner", "scan_images")],
    ];
    const diagnostics = [
      ["Dernière synchronisation", value("main", "last_successful_update")],
      ["Copies couleur", value("copy", "color_impressions")],
      ["Copies noir et blanc", value("copy", "monochrome_impressions")],
      ["Impressions couleur", value("printer", "color_impressions")],
      ["Impressions noir et blanc", value("printer", "monochrome_impressions")],
      ["Recto verso", value("printer", "duplex_sheets")],
      ["Bourrages papier", value("printer", "jam_events")],
      ["Incidents d’alimentation papier", value("printer", "mispick_events")],
      ["ePrint enregistré", value("eprint", "registration_state")],
    ];
    const inkRows = available.filter((e) => e.unique_id?.endsWith("_sensor_consumable_percentage_level_remaining") ||
      e.unique_id?.endsWith("_sensor_consumable_raw_percentage_level_remaining"));
    const ink = inkRows.map((e) => ({ name: e.entity_id.split(".")[1].replace(/_/g, " "), state: this._hass.states[e.entity_id]?.state }))
      .filter((item) => item.state && !["unknown", "unavailable"].includes(item.state));
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
    const pct = (v) => Math.max(0, Math.min(100, Number(v) || 0));
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding:20px; color:var(--primary-text-color); }
        header { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:16px; }
        h2 { margin:0; font-size:20px; font-weight:600; }
        .status { color:var(--secondary-text-color); font-size:13px; }
        .grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; }
        .metric { background:var(--secondary-background-color); border-radius:12px; padding:12px 8px; text-align:center; }
        .metric strong { display:block; font-size:20px; margin-bottom:4px; }
        .metric span { color:var(--secondary-text-color); font-size:12px; }
        h3 { font-size:14px; margin:18px 0 10px; }
        .ink { margin-bottom:12px; font-size:13px; }
        .ink-label { display:flex; justify-content:space-between; margin-bottom:6px; }
        .track { background:var(--divider-color); border-radius:20px; height:9px; overflow:hidden; }
        .fill { height:100%; background:var(--primary-color); border-radius:20px; }
        details { margin-top:18px; border-top:1px solid var(--divider-color); padding-top:12px; }
        summary { cursor:pointer; font-weight:600; }
        .diag-row { display:flex; justify-content:space-between; gap:12px; padding:8px 0; border-bottom:1px solid var(--divider-color); font-size:13px; }
        .hint { color:var(--secondary-text-color); font-size:13px; }
      </style>
      <ha-card>
        <header><h2>${esc(this._config.title || "HP Printer")}</h2><span class="status">${esc(status)}</span></header>
        ${!available.length ? '<p class="hint">Aucune entité HP Printer détectée. Vérifiez que l’intégration est chargée.</p>' : ""}
        <h3>Compteurs</h3>
        <div class="grid">${printers.map(([name, count]) => `<div class="metric"><strong>${esc(count)}</strong><span>${esc(name)}</span></div>`).join("")}</div>
        <h3>Cartouches</h3>
        ${ink.length ? ink.map((i) => `<div class="ink"><div class="ink-label"><span>${esc(i.name)}</span><b>${esc(i.state)} %</b></div><div class="track"><div class="fill" style="width:${pct(i.state)}%"></div></div></div>`).join("") : '<p class="hint">Niveaux non disponibles.</p>'}
        <details><summary>Diagnostics</summary>${diagnostics.map(([name, count]) => `<div class="diag-row"><span>${esc(name)}</span><strong>${esc(count)}</strong></div>`).join("")}</details>
      </ha-card>`;
  }
}
customElements.define("hpprinter-card", HPPrinterCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "hpprinter-card", name: "HP Printer", description: "Printer status, ink levels and usage counters" });

class HPPrinterCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  _render() {
    if (!this._config) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = '<label>Card title <input type="text"></label><p>For multiple printers, set entry_id in YAML.</p>';
    const input = this.shadowRoot.querySelector("input");
    input.value = this._config.title || "";
    input.addEventListener("change", () => {
      this._config = { ...this._config, title: input.value };
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
    });
  }
}
customElements.define("hpprinter-card-editor", HPPrinterCardEditor);
