import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const classes = new Map();
class Element {
  attachShadow() {
    this.shadowRoot = {
      innerHTML: "",
      querySelector: () => null,
    };
  }
}
const context = {
  HTMLElement: Element,
  customElements: { define: (name, cls) => classes.set(name, cls) },
  window: {},
  TextDecoder,
  navigator: { language: "fr-FR" },
};
vm.runInNewContext(
  readFileSync(new URL("../custom_components/hpprinter/www/hpprinter-card.js", import.meta.url), "utf8"),
  context,
);

function fixture(status = "ready", entryId = "printer") {
  const card = new (classes.get("hpprinter-card"))();
  const entries = [];
  const states = {};
  function add(device, key, state, domain = "sensor", entry = entryId) {
    const entity_id = `${domain}.${entry}_${device}_${key}`;
    entries.push({ entity_id, unique_id: `${entry}_${device}_${domain}_${key}`, config_entry_id: entry, platform: "hpprinter" });
    states[entity_id] = { state, attributes: {} };
    return entity_id;
  }
  const statusId = add("main", "device_status", status);
  add("main", "wifi_connected", "on", "binary_sensor");
  add("main", "wifi_ssid", "54657374");
  add("main", "wifi_signal_dbm", "-55");
  add("printer", "total_impressions", "42");
  card._registry = entries;
  card.setConfig({ entry_id: entryId });
  card.hass = { states, locale: { language: "fr-FR" } };
  return { card, add, states, statusId, html: () => card.shadowRoot.innerHTML };
}

test("online diagnostics show live values and decoded SSID", () => {
  const { html } = fixture();
  assert.match(html(), /class="status">ready</);
  assert.match(html(), /SSID Wi-Fi<\/span><strong>Test</);
  assert.match(html(), /Interface Wi-Fi<\/span><strong>Connectée</);
  assert.doesNotMatch(html(), /dernières valeurs connues|class="diag-row stale"/);
});

for (const status of ["off", "OFF", "offline", "unknown", "unavailable"]) {
  test(`cached network diagnostics for ${status}`, () => {
    const { html } = fixture(status);
    assert.match(html(), /Diagnostics réseau : dernières valeurs connues/);
    assert.match(html(), /class="diag-row stale"><span>Signal Wi-Fi \(dBm\)<\/span><strong>-55</);
    assert.match(html(), /Connectée \(dernier état connu\)/);
    assert.match(html(), /<strong>42<\/strong><span>Impressions/);
    assert.doesNotMatch(html(), /class="diag-row stale"><span>Canal Wi-Fi/);
  });
}

test("reconnection removes cached-state markers", () => {
  const { card, states, statusId, html } = fixture("off");
  states[statusId].state = "ready";
  card.hass = { states };
  assert.doesNotMatch(html(), /dernières valeurs connues|dernier état connu|class="diag-row stale"/);
});

test("consumables filter unavailable states and clamp bar widths", () => {
  const { card, add, states, html } = fixture();
  add("consumable_K", "consumable_percentage_level_remaining", "0");
  add("consumable_C", "consumable_percentage_level_remaining", "120");
  add("consumable_M", "consumable_percentage_level_remaining", "-5");
  add("consumable_Y", "consumable_percentage_level_remaining", "unavailable");
  card.hass = { states };
  assert.match(html(), /Noir<\/span><b>0 %/);
  assert.match(html(), /fill black" style="width:0%"/);
  assert.match(html(), /fill cyan" style="width:100%"/);
  assert.match(html(), /fill magenta" style="width:0%"/);
  assert.doesNotMatch(html(), /<span>Jaune<\/span>/);
});

test("configured printer is isolated from other entries", () => {
  const { card, add, states, html } = fixture();
  add("printer", "total_impressions", "999", "sensor", "other");
  card.hass = { states };
  assert.match(html(), /<strong>42<\/strong><span>Impressions/);
  assert.doesNotMatch(html(), /999/);
});

test("title is escaped and diagnostics remain open on refresh", () => {
  const { card, html } = fixture();
  card.shadowRoot.querySelector = () => ({ open: true });
  card.setConfig({ title: "<script>&" });
  assert.match(html(), /&lt;script&gt;&amp;/);
  assert.match(html(), /<details open>/);
  assert.doesNotMatch(html(), /<script>/);
});
