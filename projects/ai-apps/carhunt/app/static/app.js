/* Carhunt — webapp (vanilla JS, nessun build step: gira anche su un Pi Zero) */

const state = {
  meta: null,
  searches: [],
  current: null,
  listings: [],
};

const $ = (id) => document.getElementById(id);

const CRITERIA_TEXT = ["make", "model", "keywords", "gearbox", "seller", "region"];
const CRITERIA_NUM = ["price_min", "price_max", "year_min", "year_max", "km_max", "power_min",
                      "home_lat", "home_lon", "max_distance_km"];
const CRITERIA_LIST = ["fuels", "must_have", "nice_to_have", "exclude"];

/* --------------------------------------------------------------------- api */
async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `Errore ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

function toast(message, kind = "ok", ms = 4000) {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast ${kind}`;
  el.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { el.hidden = true; }, ms);
}

async function withBusy(button, fn) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "…";
  try { return await fn(); }
  catch (error) { toast(error.message, "error", 7000); }
  finally { button.disabled = false; button.textContent = label; }
}

/* ------------------------------------------------------------------ format */
const euro = (value) => value == null ? "—" : `${Math.round(value).toLocaleString("it-IT")} €`;
const km = (value) => value == null ? "—" : `${Math.round(value).toLocaleString("it-IT")} km`;

function timeAgo(iso) {
  if (!iso) return "";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "adesso";
  if (minutes < 60) return `${minutes} min fa`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h fa`;
  return `${Math.round(hours / 24)} g fa`;
}

/* -------------------------------------------------------------------- meta */
async function loadMeta() {
  state.meta = await api("/meta");
  const { interval_minutes, telegram_configured, next_run } = state.meta;
  $("interval").textContent = interval_minutes === 60 ? "ogni ora" : `ogni ${interval_minutes} minuti`;
  const parts = [
    telegram_configured ? "✅ Telegram configurato" : "⚠️ Telegram non configurato (vedi .env)",
    next_run ? `prossimo controllo ${new Date(next_run).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}` : "scheduler in avvio",
  ];
  $("status").textContent = parts.join(" · ");

  $("providers").innerHTML = state.meta.providers.map((p) => `
    <label><input type="checkbox" class="provider" value="${p.key}"> ${p.label}</label>
  `).join("");
}

/* ---------------------------------------------------------------- ricerche */
async function loadSearches(selectId = null) {
  state.searches = await api("/searches");
  renderSearchList();
  const target = selectId || (state.current && state.current.id) || (state.searches[0] && state.searches[0].id);
  if (target) selectSearch(target);
  else { $("detail").hidden = true; $("empty").hidden = false; }
}

function renderSearchList() {
  $("search-list").innerHTML = state.searches.map((s) => `
    <li data-id="${s.id}" class="${state.current && state.current.id === s.id ? "active" : ""} ${s.enabled ? "" : "off"}">
      <span>${escapeHtml(s.name)}</span>
      <span class="meta">${s.enabled ? "attiva" : "in pausa"} · ${s.last_run_at ? "ultimo giro " + timeAgo(s.last_run_at) : "mai eseguita"}</span>
    </li>`).join("");
  [...document.querySelectorAll(".search-list li")].forEach((li) => {
    li.onclick = () => selectSearch(Number(li.dataset.id));
  });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function selectSearch(id) {
  const search = state.searches.find((s) => s.id === id);
  if (!search) return;
  state.current = search;
  $("empty").hidden = true;
  $("detail").hidden = false;
  fillForm(search);
  renderSearchList();
  await loadListings();
}

function fillForm(search) {
  $("f-name").value = search.name;
  $("f-enabled").checked = search.enabled;
  $("f-chat").value = search.telegram_chat_id || "";
  $("f-min_score").value = search.min_score ?? 60;
  $("f-min_score-out").textContent = `${search.min_score ?? 60}/100`;

  const criteria = search.criteria || {};
  CRITERIA_TEXT.forEach((key) => { $(`c-${key}`).value = criteria[key] || ""; });
  CRITERIA_NUM.forEach((key) => { $(`c-${key}`).value = criteria[key] ?? ""; });
  CRITERIA_LIST.forEach((key) => { $(`c-${key}`).value = (criteria[key] || []).join(", "); });

  const selected = criteria.providers && criteria.providers.length
    ? criteria.providers
    : state.meta.providers.filter((p) => p.needs_network).map((p) => p.key);
  document.querySelectorAll(".provider").forEach((box) => { box.checked = selected.includes(box.value); });

  renderWeights(search.weights);
}

function renderWeights(weights) {
  const { weight_keys, weight_labels } = state.meta;
  $("weights").innerHTML = weight_keys.map((key) => `
    <div class="weight">
      <div class="weight-head"><b>${weight_labels[key]}</b><span class="value" id="w-out-${key}">${weights[key]}</span></div>
      <input type="range" min="0" max="10" step="1" id="w-${key}" value="${weights[key]}">
    </div>`).join("");
  weight_keys.forEach((key) => {
    $(`w-${key}`).oninput = () => {
      $(`w-out-${key}`).textContent = $(`w-${key}`).value;
      scheduleSimulation();
    };
  });
}

function collectForm() {
  const criteria = {};
  CRITERIA_TEXT.forEach((key) => { criteria[key] = $(`c-${key}`).value.trim(); });
  CRITERIA_NUM.forEach((key) => {
    const raw = $(`c-${key}`).value;
    criteria[key] = raw === "" ? null : Number(raw);
  });
  CRITERIA_LIST.forEach((key) => {
    criteria[key] = $(`c-${key}`).value.split(",").map((v) => v.trim()).filter(Boolean);
  });
  criteria.providers = [...document.querySelectorAll(".provider:checked")].map((b) => b.value);

  const weights = {};
  state.meta.weight_keys.forEach((key) => { weights[key] = Number($(`w-${key}`).value); });

  return {
    name: $("f-name").value.trim() || "Ricerca senza nome",
    enabled: $("f-enabled").checked,
    telegram_chat_id: $("f-chat").value.trim(),
    min_score: Number($("f-min_score").value),
    criteria,
    weights,
  };
}

/* ---------------------------------------------------------------- annunci */
async function loadListings() {
  if (!state.current) return;
  state.listings = await api(`/searches/${state.current.id}/listings`);
  renderResults();
}

let simulationTimer = null;
function scheduleSimulation() {
  clearTimeout(simulationTimer);
  simulationTimer = setTimeout(runSimulation, 350);
}

async function runSimulation() {
  if (!state.current || !state.listings.length) return;
  const payload = collectForm();
  try {
    state.listings = await api(`/searches/${state.current.id}/simulate`, {
      method: "POST",
      body: JSON.stringify({ weights: payload.weights, criteria: payload.criteria }),
    });
    renderResults(true);
  } catch (error) {
    toast(error.message, "error");
  }
}

function sortListings(items) {
  const mode = $("sort").value;
  const copy = [...items];
  const comparators = {
    score: (a, b) => (b.score ?? 0) - (a.score ?? 0),
    deal: (a, b) => (b.deal_delta ?? -9) - (a.deal_delta ?? -9),
    price: (a, b) => (a.price ?? Infinity) - (b.price ?? Infinity),
    km: (a, b) => (a.mileage ?? Infinity) - (b.mileage ?? Infinity),
    recent: (a, b) => String(b.first_seen_at).localeCompare(String(a.first_seen_at)),
  };
  return copy.sort(comparators[mode] || comparators.score);
}

function renderResults(simulated = false) {
  const threshold = Number($("f-min_score").value);
  let items = state.listings;
  if ($("only-good").checked) items = items.filter((l) => (l.score ?? 0) >= threshold);
  items = sortListings(items);

  $("results-count").textContent = `${items.length}${simulated ? " · anteprima con i pesi attuali" : ""}`;
  if (!items.length) {
    $("results").innerHTML = `<p class="hint">Nessun annuncio ancora. Premi “Cerca ora” per il primo giro.</p>`;
    return;
  }

  $("results").innerHTML = items.map(renderCard).join("");
}

function renderCard(listing) {
  const score = listing.score ?? 0;
  const badge = score >= 70 ? "good" : score >= 50 ? "mid" : "bad";
  const delta = listing.deal_delta;
  const pct = delta == null ? null : Math.abs(delta * 100);
  const dealChip = delta == null ? ""
    : pct < 1 ? '<span class="chip">in linea col mercato</span>'
    : `<span class="chip ${delta >= 0.04 ? "deal-good" : delta <= -0.04 ? "deal-bad" : ""}">
       ${delta >= 0 ? "−" : "+"}${pct.toFixed(0)}% vs mercato</span>`;
  const isNew = listing.first_seen_at &&
    (Date.now() - new Date(listing.first_seen_at).getTime()) < 26 * 3600 * 1000;

  const specs = [
    listing.year, listing.mileage != null ? km(listing.mileage) : null,
    listing.fuel, listing.gearbox, listing.power_hp ? `${listing.power_hp} CV` : null,
    listing.location, listing.seller,
  ].filter(Boolean);

  return `
    <article class="card ${score >= 75 ? "top" : ""}">
      <div class="card-head">
        <div class="badge ${badge}">${score.toFixed(0)}<small>/100</small></div>
        <div class="card-title">
          ${listing.url ? `<a href="${escapeHtml(listing.url)}" target="_blank" rel="noopener">${escapeHtml(listing.title)}</a>`
                        : escapeHtml(listing.title)}
          <div class="verdict">${escapeHtml(listing.verdict || "")}</div>
        </div>
      </div>
      <div class="price">${euro(listing.price)}
        ${listing.estimated_price ? `<span class="chip">stima ${euro(listing.estimated_price)}</span>` : ""}
      </div>
      <div class="chips">
        ${isNew ? '<span class="chip new">nuovo</span>' : ""}
        ${dealChip}
        ${specs.map((s) => `<span class="chip">${escapeHtml(s)}</span>`).join("")}
      </div>
      <p class="comment">${escapeHtml(listing.comment || "")}</p>
      <div class="card-foot">
        <span>${escapeHtml(listing.provider)}</span>
        <span>${listing.notified_at ? "🔔 notificato" : ""} · visto ${timeAgo(listing.first_seen_at)}</span>
      </div>
    </article>`;
}

/* ------------------------------------------------------------------ azioni */
function newSearch() {
  const defaults = {
    id: null,
    name: "Nuova ricerca",
    enabled: true,
    min_score: 65,
    telegram_chat_id: "",
    criteria: { providers: state.meta.providers.filter((p) => p.needs_network).map((p) => p.key),
                exclude: ["incidentata", "per ricambi"] },
    weights: { ...state.meta.default_weights },
  };
  state.current = defaults;
  state.listings = [];
  $("empty").hidden = true;
  $("detail").hidden = false;
  fillForm(defaults);
  renderResults();
  renderSearchList();
  $("f-name").focus();
  $("f-name").select();
}

async function save(button) {
  await withBusy(button, async () => {
    const payload = collectForm();
    const saved = state.current && state.current.id
      ? await api(`/searches/${state.current.id}`, { method: "PUT", body: JSON.stringify(payload) })
      : await api("/searches", { method: "POST", body: JSON.stringify(payload) });
    state.current = saved;
    await loadSearches(saved.id);
    toast("Ricerca salvata.");
  });
}

async function runCurrent(button) {
  if (!state.current || !state.current.id) { toast("Salva prima la ricerca.", "error"); return; }
  await withBusy(button, async () => {
    const result = await api(`/searches/${state.current.id}/run`, { method: "POST" });
    await loadListings();
    await loadSearches(state.current.id);
    const errors = result.errors && result.errors.length ? ` — problemi: ${result.errors.join("; ")}` : "";
    toast(`Trovati ${result.found} annunci · ${result.new} nuovi · ${result.notified} notifiche${errors}`,
          errors ? "error" : "ok", 8000);
  });
}

/* -------------------------------------------------------------------- boot */
async function boot() {
  await loadMeta();
  await loadSearches();

  $("btn-new").onclick = newSearch;
  $("btn-new-2").onclick = newSearch;
  $("btn-save").onclick = (e) => save(e.target);
  $("btn-run").onclick = (e) => runCurrent(e.target);
  $("btn-delete").onclick = async (e) => {
    if (!state.current || !state.current.id) return;
    if (!confirm(`Elimino la ricerca “${state.current.name}” e i suoi annunci?`)) return;
    await withBusy(e.target, async () => {
      await api(`/searches/${state.current.id}`, { method: "DELETE" });
      state.current = null;
      await loadSearches();
      toast("Ricerca eliminata.");
    });
  };
  $("btn-run-all").onclick = (e) => withBusy(e.target, async () => {
    const results = await api("/run-all", { method: "POST" });
    await loadSearches(state.current && state.current.id);
    await loadMeta();
    const totals = results.reduce((acc, r) => ({ found: acc.found + (r.found || 0), nuovi: acc.nuovi + (r.new || 0) }),
                                  { found: 0, nuovi: 0 });
    toast(`Giro completato su ${results.length} ricerche: ${totals.found} annunci, ${totals.nuovi} nuovi.`);
  });
  $("btn-telegram").onclick = (e) => withBusy(e.target, async () => {
    await api("/telegram/test", { method: "POST", body: JSON.stringify({ chat_id: $("f-chat").value.trim() }) });
    toast("Messaggio di prova inviato su Telegram.");
  });

  $("f-min_score").oninput = () => {
    $("f-min_score-out").textContent = `${$("f-min_score").value}/100`;
    renderResults();
  };
  $("sort").onchange = () => renderResults();
  $("only-good").onchange = () => renderResults();
}

boot().catch((error) => toast(`Avvio fallito: ${error.message}`, "error", 10000));
