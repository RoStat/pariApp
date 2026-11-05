/* PariApp v2 — lit data/offre.json, value.json, summary.json du relais GitHub, génère des tickets combinés
   Parions Sport point de vente et les liens adj.st. Aucun framework, aucun build. Port de la v1 (artefact sql.js). */
"use strict";

// ---------- source de données ----------
const REPO = { owner: "RoStat", name: "pariApp", branch: "main" };
const qs = new URLSearchParams(location.search);
if (qs.get("branch")) REPO.branch = qs.get("branch");
const DATA_BASE = qs.get("data") || `https://raw.githubusercontent.com/${REPO.owner}/${REPO.name}/${REPO.branch}/data/`;
const RAW = (f) => DATA_BASE + f + (DATA_BASE.startsWith("http") ? "?t=" + Date.now() : "");
const ADJ = "&adj_t=1toqzbnl&pr=0";
const MARGE_SCAN_MIN = 45;        // un match dont la validation ferme dans moins de 45 min est exclu (temps d'aller scanner)
const OFFRE_VIEILLE_MIN = 60;     // au-delà, bandeau d'alerte
const MAX_LEGS = 12;

// TRJ (taux de retour joueur) mesuré ou prudent par marché, offre point de vente — un seul objet, à ajuster ici.
// 1N2/DC/OU25/BTTS : mesurés sur l'offre du 05/11/2026 ; buteur/doublé/décisif : estimations prudentes (marchés joueurs plus chargés).
const TRJ = { "1N2": 0.843, DC: 0.901, OU25: 0.832, BTTS: 0.824, team_total: 0.83, buteur: 0.75, double: 0.70, decisif: 0.75, double_match: 0.80 };
const TRJ_KEY = { fav: "1N2", outsider: "1N2", nul: "1N2", dc: "DC", total: "OU25", btts: "BTTS", buts_eq: "team_total", buteur: "buteur", double: "double", decisif: "decisif", double_match: "double_match" };
const TYPES = { fav: "1N2", outsider: "Outsider", nul: "Nul", dc: "Dbl chance", buts_eq: "Buts équipe", total: "+/- 2,5", buteur: "Buteur", double: "Doublé", decisif: "Décisif", double_match: "Doublé match", btts: "2 marquent" };
// Libellé de marché tel qu'attendu par journal/tickets.csv et clv.py
const MARKET_LIB = { fav: "1/N/2", outsider: "1/N/2", nul: "1/N/2", dc: "Double chance", total: "Plus/Moins 2,5", btts: "Les 2 équipes marquent", buts_eq: "Plus/Moins équipe", buteur: "Buteur", double: "Buteur 2 fois ou plus", decisif: "Joueur décisif", double_match: "Un doublé sera-t-il marqué ?" };

const STEPS = ["Accueil", "Périmètre", "Compétitions", "Réglages", "Matchs", "Tickets"];
const S = {
  step: 0, offre: null, summary: null, value: null, events: [], byId: {}, legsByEvent: {}, valueByKey: {},
  scope: "soir", compsOn: new Set(), evOff: new Set(), tickets: [], loadError: null,
  prefs: { nb: 5, mise: 3, gmin: 200, gmax: 2000, style: "melange", favComps: [], budgetHebdo: 30 }
};
const ls = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { } } };
Object.assign(S.prefs, ls.get("pariapp.prefs", {}));
S.scope = ls.get("pariapp.scope", "soir");
// tickets validés : {key, name, date, validated_at, mise, cote, legs:[{event_id, match, market, pick, market_id, pos, cote}]}
let validated = ls.get("pariapp.validated.v2", []);
const saveValidated = () => ls.set("pariapp.validated.v2", validated);

const $ = (s, r = document) => r.querySelector(s);
const el = (h) => { const t = document.createElement("template"); t.innerHTML = h.trim(); return t.content.firstChild; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (n, d = 2) => Number(n).toLocaleString("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: d });
const pct = (x) => Math.round(x * 100) + " %";
const hm = (ts) => new Date(ts * 1000).toLocaleString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const dm = (iso) => new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const toast = (m) => { const t = $("#toast"); t.textContent = m; t.style.display = "block"; setTimeout(() => t.style.display = "none", 2400); };
const savePrefs = () => ls.set("pariapp.prefs", S.prefs);
const nowS = () => Date.now() / 1000;
const copy = (txt, okMsg) => navigator.clipboard.writeText(txt).then(() => toast(okMsg)).catch(() => toast("Copie refusée par le navigateur"));

// ---------- chargement ----------
async function fetchJson(name, optional) {
  try {
    const r = await fetch(RAW(name), { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const j = await r.json();
    ls.set("pariapp.cache." + name, j);
    return j;
  } catch (e) {
    const cached = ls.get("pariapp.cache." + name, null);
    if (cached) { S.loadError = S.loadError || `${name} : ${e.message} (copie locale utilisée)`; return cached; }
    if (optional) return null;
    throw new Error(`${name} : ${e.message}`);
  }
}
async function load() {
  render(0, "Chargement des données…");
  try {
    const [offre, summary, value] = await Promise.all([fetchJson("offre.json"), fetchJson("summary.json", true), fetchJson("value.json", true)]);
    S.offre = offre; S.summary = summary || {}; S.value = value || { rows: [], picks: [], min_value_pct: 3 };
    prepare();
    render(0);
  } catch (e) { S.loadError = e.message; render(0, "Impossible de lire l'offre relayée : " + e.message); }
}
function offreAgeMin() { return S.offre?.offer_created_at ? (Date.now() - Date.parse(S.offre.offer_created_at)) / 60000 : null; }

// ---------- préparation du pool de jambes ----------
function prepare() {
  const limit = nowS() + MARGE_SCAN_MIN * 60;
  S.events = S.offre.events.filter(e => e.fin_ts > limit && e.markets["1N2"]).sort((a, b) => a.start_ts - b.start_ts || a.match.localeCompare(b.match));
  S.byId = {}; S.events.forEach(e => S.byId[e.event_id] = e);
  S.valueByKey = {};
  (S.value.rows || []).forEach(r => { S.valueByKey[r.market_id + ":" + r.pos] = r; });
  const minV = S.value.min_value_pct ?? 3;
  const L = {};
  const add = (e, type, label, mk, o, player, pickLib) => {
    const v = S.valueByKey[mk.market_id + ":" + o.pos];
    (L[e.event_id] ||= []).push({ ev: e.event_id, type, label, cote: o.cote, mid: mk.market_id, pos: o.pos, player: player || null,
      market: MARKET_LIB[type], pick: pickLib || o.lib, value: v ? v.value_pct : null, isValue: !!(v && v.value_pct >= minV) });
  };
  S.events.forEach(e => {
    const m = e.markets; const home = e.home, away = e.away;
    const o1n2 = m["1N2"].outcomes;
    const h = o1n2.find(o => o.lib === "1"), n = o1n2.find(o => o.lib === "N"), a = o1n2.find(o => o.lib === "2");
    if (h && n && a) {
      const fav = h.cote <= a.cote ? h : a, dog = fav === h ? a : h;
      if (fav.cote >= 1.12 && fav.cote <= 1.8) add(e, "fav", (fav === h ? home : away) + " gagne", m["1N2"], fav);
      if (dog.cote >= 2.4 && dog.cote <= 4.6) add(e, "outsider", (dog === h ? home : away) + " gagne", m["1N2"], dog);
      if (n.cote >= 3 && n.cote <= 4.3) add(e, "nul", "Match nul", m["1N2"], n);
    }
    if (m.DC) m.DC.outcomes.forEach(o => { if (o.cote >= 1.15 && o.cote <= 1.65) add(e, "dc", { "1/N": home + " ou nul", "N/2": away + " ou nul", "1/2": "Pas de nul" }[o.lib] || o.lib, m.DC, o); });
    if (m.OU25) m.OU25.outcomes.forEach(o => { const plus = /^Plus/.test(o.lib); if (o.cote <= 1.75) add(e, "total", plus ? "+2,5 buts dans le match" : "−2,5 buts dans le match", m.OU25, o); });
    if (m.BTTS) m.BTTS.outcomes.forEach(o => { if (o.cote <= 1.8) add(e, "btts", o.lib === "Oui" ? "Les 2 équipes marquent" : "Une équipe ne marque pas", m.BTTS, o); });
    (m.team_totals || []).forEach(tt => { const p = tt.outcomes.find(o => /^Plus/.test(o.lib)); if (p && p.cote >= 1.12 && p.cote <= 2.6) add(e, "buts_eq", tt.team + " +" + tt.line + " buts", { market_id: tt.market_id }, p); });
    if (m.buteur) m.buteur.outcomes.slice().sort((x, y) => x.cote - y.cote).slice(0, 2).filter(o => o.cote <= 2.3).forEach(o => add(e, "buteur", o.lib + " buteur", m.buteur, o, o.lib));
    if (m.double) m.double.outcomes.slice().sort((x, y) => x.cote - y.cote).slice(0, 2).filter(o => o.cote <= 4.6).forEach(o => add(e, "double", o.lib + " doublé", m.double, o, o.lib));
    if (m.decisif) m.decisif.outcomes.slice().sort((x, y) => x.cote - y.cote).slice(0, 2).filter(o => o.cote <= 1.85).forEach(o => add(e, "decisif", o.lib + " décisif (but ou passe)", m.decisif, o, o.lib));
    if (m.double_match) { const o = m.double_match.outcomes.find(o => o.lib === "Oui"); if (o && o.cote <= 1.85) add(e, "double_match", "Un doublé dans le match", m.double_match, o); }
  });
  S.legsByEvent = L;
  const created = S.offre.offer_created_at ? dm(S.offre.offer_created_at) : "?";
  $("#offreInfo").textContent = "offre du " + created;
}

// ---------- périmètre ----------
function scopeBounds() {
  const d = new Date(); const end = new Date(d); end.setHours(5, 0, 0, 0); if (end <= d) end.setDate(end.getDate() + 1);
  const days = { soir: 0, demain: 1, trois: 2, tout: 60 }[S.scope] ?? 0; end.setDate(end.getDate() + days);
  return [nowS(), end.getTime() / 1000];
}
const eventsInScope = () => { const [a, b] = scopeBounds(); return S.events.filter(e => e.start_ts >= a - 3600 && e.start_ts <= b); };
const compsInScope = () => { const c = {}; eventsInScope().forEach(e => { c[e.comp_id] ||= { id: e.comp_id, comp: e.comp, n: 0, first: e.start_ts, followed: e.followed }; c[e.comp_id].n++; }); return Object.values(c).sort((x, y) => (y.followed - x.followed) || y.n - x.n); };
const selectedEvents = () => eventsInScope().filter(e => S.compsOn.has(e.comp_id) && !S.evOff.has(e.event_id));

// ---------- générateur ----------
// w = poids de tirage par type ; maxLeg = cote max d'une jambe ; minTypes = diversité minimale ; legs = [min, max] ;
// coteRange (Discipliné) remplace la fourchette de gains ; only = types autorisés.
const STYLES = {
  melange:    { w: { fav: 3, outsider: 1.2, nul: 1.2, dc: 0.6, buts_eq: 2, total: 1, buteur: 2, double: 1, decisif: 2, double_match: 1, btts: 1 }, maxLeg: 4.6, minTypes: 4, legs: [4, 10] },
  safe:       { w: { fav: 4, dc: 2, buts_eq: 3, total: 2, decisif: 3, buteur: 1, btts: 1, double_match: 1 }, maxLeg: 1.8, minTypes: 3, legs: [6, 12] },
  risque:     { w: { outsider: 3, nul: 3, double: 3, buteur: 2, buts_eq: 1, fav: 1, total: 0.5 }, maxLeg: 4.6, minTypes: 3, legs: [3, 7] },
  discipline: { w: { fav: 3, dc: 3, total: 2, btts: 2, nul: 0.4, outsider: 0.4 }, maxLeg: 3.0, minTypes: 1, legs: [2, 3], coteRange: [3, 8] }
};
const STYLE_LABELS = { melange: "Mélange", safe: "Safe", risque: "Risqué", discipline: "Discipliné" };
function pickWeighted(items, wf) { let tot = 0; const ws = items.map(i => { const w = wf(i); tot += w; return w; }); let r = Math.random() * tot; for (let i = 0; i < items.length; i++) { r -= ws[i]; if (r <= 0) return items[i]; } return items[items.length - 1]; }
function legWeight(cfg, l, legs, usedEv) {
  let w = cfg.w[l.type] || 0;
  if (!w) return 0;
  if (l.isValue) w *= 2.5;                       // préférence pour les jambes à valeur positive (Pinnacle)
  else if (l.value != null && l.value < -8) w *= 0.5; // jambe nettement surcotée par FDJ
  if (usedEv[l.ev]) w *= 0.25;                   // match déjà utilisé par un autre ticket
  if (legs.some(x => x.type === l.type)) w *= 0.5; // diversité des types
  return w;
}
function genTicket(pool, cfg, cmin, cmax, usedEv, usedPl) {
  let best = null;
  const maxLegs = Math.min(cfg.legs[1], MAX_LEGS);
  for (let attempt = 0; attempt < 400; attempt++) {
    const legs = []; const evs = new Set(); let cote = 1;
    for (let i = 0; i < maxLegs; i++) {
      const cands = pool.filter(l => !evs.has(l.ev) && cfg.w[l.type] && l.cote <= cfg.maxLeg && (!l.player || (usedPl[l.player] || 0) < 2) && cote * l.cote <= cmax * 1.02);
      if (!cands.length) break;
      const leg = pickWeighted(cands, l => legWeight(cfg, l, legs, usedEv));
      legs.push(leg); evs.add(leg.ev); cote *= leg.cote;
      if (cote >= cmin && legs.length >= cfg.legs[0]) break;
    }
    if (cote < cmin || cote > cmax || legs.length < cfg.legs[0]) continue;
    const types = new Set(legs.map(l => l.type)).size; if (types < Math.min(cfg.minTypes, legs.length)) continue;
    const overlap = legs.filter(l => usedEv[l.ev]).length;
    const nValue = legs.filter(l => l.isValue).length;
    const score = types - 0.12 * legs.length - 0.8 * overlap + 0.5 * nValue + Math.random() * 0.3;
    if (!best || score > best.score) best = { legs, cote, score };
  }
  return best;
}
function nameTicket(legs, taken, style) {
  const c = {}; legs.forEach(l => c[l.type] = (c[l.type] || 0) + 1);
  const goals = (c.buts_eq || 0) + (c.total || 0) + (c.double_match || 0) + (c.btts || 0);
  let n = "Le classique";
  if (style === "discipline") n = "Le discipliné";
  else if (legs.length <= 4) n = "Court et piquant";
  else if ((c.outsider || 0) + (c.nul || 0) >= 2) n = "Les outsiders ont des dents";
  else if (goals >= legs.length / 2) n = "Pluie de buts";
  else if ((c.double || 0) + (c.buteur || 0) >= 3) n = "Les stars";
  const alt = ["Le funambule", "La tournée des stades", "Le métronome", "L'audacieux", "Le fil du rasoir", "La belle équipe", "Le coup de poker", "Le grand huit", "Le sobre", "Le posé"];
  let k = n, i = 0; while (taken.has(k)) { k = alt[i % alt.length] + (i >= alt.length ? " " + (Math.floor(i / alt.length) + 1) : ""); i++; } taken.add(k); return k;
}
function targetRange(cfg) { return cfg.coteRange ? cfg.coteRange : [S.prefs.gmin / S.prefs.mise, S.prefs.gmax / S.prefs.mise]; }
function buildPool() { const pool = []; selectedEvents().forEach(e => (S.legsByEvent[e.event_id] || []).forEach(l => pool.push(l))); return pool; }
function generateAll() {
  const pool = buildPool(); const cfg = STYLES[S.prefs.style] || STYLES.melange; const [cmin, cmax] = targetRange(cfg);
  const usedEv = {}, usedPl = {}, taken = new Set(); S.tickets = [];
  for (let k = 0; k < S.prefs.nb; k++) {
    const t = genTicket(pool, cfg, cmin, cmax, usedEv, usedPl); if (!t) break;
    t.legs.forEach(l => { usedEv[l.ev] = (usedEv[l.ev] || 0) + 1; if (l.player) usedPl[l.player] = (usedPl[l.player] || 0) + 1; });
    S.tickets.push(finishTicket(t.legs, nameTicket(t.legs, taken, S.prefs.style)));
  }
}
// Combi Boosté (grille de l'offre) : bonus sur le gain net si n >= 4 sélections et chaque cote >= min_cote ; plafond du bonus.
function boostFor(legs) {
  const b = S.offre.boost || {}; if (!b.enabled || !b.grid_pct) return 0;
  if (legs.length < 4 || legs.some(l => l.cote < (b.min_cote || 1.2))) return 0;
  return (b.grid_pct[String(legs.length)] || 0) / 100;
}
function finishTicket(legs, name) {
  legs = legs.slice().sort((a, b) => S.byId[a.ev].start_ts - S.byId[b.ev].start_ts);
  const cote = legs.reduce((p, l) => p * l.cote, 1);
  const boost = boostFor(legs); const mise = S.prefs.mise; const b = S.offre.boost || {};
  const bonus = Math.min(mise * (cote - 1) * boost, b.additional_winning_limit ?? Infinity);
  const gain = Math.min(mise * cote + bonus, b.max_win ?? Infinity);
  // TRJ effectif = produit des TRJ des marchés × multiplicateur du bonus (le bonus porte sur le gain net : 1 + boost × (1 − 1/cote))
  const trj = legs.reduce((p, l) => p * (TRJ[TRJ_KEY[l.type]] || 0.8), 1) * (1 + boost * (1 - 1 / cote));
  const link = "https://33xb.adj.st/betslip?bet_type=1&" + legs.map(l => "market_id=" + l.mid + "," + l.pos).join("&") + ADJ;
  return { name, legs, cote, boost, gain, trj, mise, deadline: Math.min(...legs.map(l => S.byId[l.ev].fin_ts)), link, key: legs.map(l => l.mid + ":" + l.pos).sort().join("|") };
}
function regenTicket(i) {
  const pool = buildPool(); const cfg = STYLES[S.prefs.style] || STYLES.melange; const usedEv = {}, usedPl = {}, taken = new Set();
  S.tickets.forEach((t, j) => { if (j === i) return; taken.add(t.name); t.legs.forEach(l => { usedEv[l.ev] = (usedEv[l.ev] || 0) + 1; if (l.player) usedPl[l.player] = (usedPl[l.player] || 0) + 1; }); });
  const [cmin, cmax] = targetRange(cfg);
  const t = genTicket(pool, cfg, cmin, cmax, usedEv, usedPl);
  if (!t) { toast("Pas d'autre combinaison possible avec ces matchs"); return; }
  S.tickets[i] = finishTicket(t.legs, nameTicket(t.legs, taken, S.prefs.style)); render(5);
}
function dropLeg(i, j) {
  const t = S.tickets[i]; if (t.legs.length <= 2) { toast("Ticket trop court : régénère plutôt"); return; }
  S.tickets[i] = finishTicket(t.legs.filter((_, k) => k !== j), t.name); render(5);
}

// ---------- tickets validés, budget hebdo, export ----------
function weekStart() { const d = new Date(); const day = (d.getDay() + 6) % 7; d.setDate(d.getDate() - day); d.setHours(0, 0, 0, 0); return d.getTime(); }
const validatedThisWeek = () => validated.filter(v => Date.parse(v.validated_at) >= weekStart());
const spentThisWeek = () => validatedThisWeek().reduce((s, v) => s + (v.mise || 0), 0);
const isValidated = (key) => validated.some(v => v.key === key);
function setValidated(t, on) {
  validated = validated.filter(v => v.key !== t.key);
  if (on) {
    const now = new Date();
    validated.push({ key: t.key, name: t.name, date: now.toISOString().slice(0, 10), validated_at: now.toISOString(), mise: t.mise, cote: t.cote,
      legs: t.legs.map(l => ({ event_id: l.ev, match: S.byId[l.ev].match, market: l.market, pick: l.pick, market_id: l.mid, pos: l.pos, cote: l.cote })) });
  }
  saveValidated();
}
function csvJournal(items) {
  const esc = (s) => String(s ?? "").replace(/[;\n\r]/g, " ");
  const lines = ["date;ticket;event_id;match;market;pick;market_id;pos;cote_prise;mise;resultat"];
  items.forEach(v => v.legs.forEach(l => lines.push([v.date, v.name, l.event_id, l.match, l.market, l.pick, l.market_id, l.pos, String(l.cote).replace(".", ","), String(v.mise).replace(".", ","), ""].map(esc).join(";"))));
  return lines.join("\n") + "\n";
}
function exportJournal() {
  const items = validated.slice().sort((a, b) => a.validated_at.localeCompare(b.validated_at));
  if (!items.length) { toast("Aucun ticket validé à exporter"); return; }
  const csv = csvJournal(items);
  copy(csv, `Journal copié (${items.length} ticket(s)) — à coller dans journal/tickets.csv`);
  try {
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" }); const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "tickets_" + new Date().toISOString().slice(0, 10) + ".csv"; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (e) { }
}
function recap() {
  return S.tickets.map(t => `${t.name} · ${t.legs.length} sél. · cote ${fmt(t.cote)} → ${fmt(t.gain)} € pour ${fmt(t.mise)} € · TRJ ${pct(t.trj)} · avant ${hm(t.deadline)}\n`
    + t.legs.map(l => `  ${hm(S.byId[l.ev].start_ts)}  ${S.byId[l.ev].match} : ${l.label} ${fmt(l.cote)}${l.isValue ? " (value)" : ""}`).join("\n") + `\n${t.link}`).join("\n\n");
}

// ---------- rendu ----------
function banner() {
  const out = []; const age = offreAgeMin(); const s = S.summary || {};
  if (S.loadError) out.push(`<div class="banner bad">${esc(S.loadError)}</div>`);
  if (age != null && age > OFFRE_VIEILLE_MIN) out.push(`<div class="banner warn">Offre relayée il y a ${Math.round(age)} min : les cotes ont pu bouger, celles de l'appli FDJ font foi.</div>`);
  if (s.last_error) out.push(`<div class="banner warn">Relais : ${esc(s.last_error)}</div>`);
  return out.join("");
}
function render(step, msg) {
  S.step = step; $("#stepbar").innerHTML = STEPS.map((s, i) => `<span class="${i <= step ? 'on' : ''}" title="${s}"></span>`).join("");
  const m = $("#main"); m.innerHTML = banner();
  if (step === 0) {
    const s = S.summary || {}; const age = offreAgeMin();
    const ko = (s.next_followed_kickoffs || []).filter(k => Date.parse(k.fin) > Date.now()).slice(0, 10);
    const spent = spentThisWeek(); const cap = S.prefs.budgetHebdo || 0;
    m.appendChild(el(`<div class="card"><h2>État des données</h2>
      ${S.offre ? `<p class="small">Offre FDJ du <b>${esc(dm(S.offre.offer_created_at))}</b> (${age != null ? Math.round(age) + " min" : "?"}), relayée ${s.fetched_at ? esc(dm(s.fetched_at)) : "?"} · ${S.events.length} matchs jouables.</p>
      <p class="small">Référence Pinnacle : ${s.last_snapshot_at ? `relevé ${esc(dm(s.last_snapshot_at))} (${esc(s.last_snapshot_kind || "")}), <b>${s.picks_count ?? 0}</b> sélection(s) à valeur positive` : "aucun relevé pour l'instant"}${s.credits_remaining != null ? ` · ${s.credits_remaining} crédits API restants` : ""}.</p>`
      : `<p class="mut">${esc(msg || "")}</p>`}
      ${cap ? `<p class="small">Budget hebdo : <b>${fmt(spent)} €</b> validés / ${fmt(cap)} €</p><div class="meter"><i class="${spent > cap ? 'over' : ''}" style="width:${Math.min(100, 100 * spent / cap)}%"></i></div>` : ""}
    </div>`));
    if (ko.length) {
      const c = el(`<div class="card"><h2>Prochains coups d'envoi suivis</h2><table class="ko"></table></div>`);
      ko.forEach(k => c.querySelector("table").appendChild(el(`<tr><td>${esc(k.match)}<br><span class="mut">${esc(k.comp)}</span></td><td>${esc(dm(k.start))}</td></tr>`)));
      m.appendChild(c);
    }
    m.appendChild(el(`<div class="card"><button class="pri" id="go" ${S.offre ? "" : "disabled"} style="width:100%">Préparer ma soirée →</button>
      <div class="row" style="margin-top:8px"><button class="sm" id="reload">Recharger les données</button><button class="sm" id="exp0">Exporter le journal (${validated.length})</button></div>
      <p class="mut small" style="margin-top:8px">Outil d'organisation : il ne crée pas d'avantage. Le TRJ point de vente est plafonné à 76,5 %, un combiné multiplie les marges ; chaque ticket affiche son TRJ effectif.</p></div>`));
    if (S.offre) $("#go").onclick = () => render(1);
    $("#reload").onclick = () => { S.loadError = null; load(); };
    $("#exp0").onclick = exportJournal;
  }
  if (step === 1) {
    const opts = [["soir", "Ce soir"], ["demain", "+ demain"], ["trois", "3 jours"], ["tout", "Tout"]];
    m.appendChild(el(`<div class="card"><h2>Périmètre</h2><div class="row">${opts.map(([k, l]) => `<span class="chip ${S.scope === k ? 'on' : ''}" data-k="${k}">${l}</span>`).join("")}</div><p class="mut" id="cnt"></p></div>`));
    const upd = () => { $("#cnt").textContent = eventsInScope().length + " matchs de football dans ce périmètre (validation possible encore ≥ 45 min)"; };
    m.querySelectorAll(".chip").forEach(c => c.onclick = () => { S.scope = c.dataset.k; ls.set("pariapp.scope", S.scope); m.querySelectorAll(".chip").forEach(x => x.classList.toggle("on", x === c)); upd(); });
    upd(); nav(m, 0, 2);
  }
  if (step === 2) {
    const comps = compsInScope();
    if (!S.compsOn.size) (S.prefs.favComps.length ? S.prefs.favComps : [45461, 45460, 46231, 45452]).forEach(id => { if (comps.some(c => c.id === id)) S.compsOn.add(id); });
    const card = el(`<div class="card"><h2>Compétitions</h2><div class="row" style="margin-bottom:6px"><button class="sm" id="all">Tout</button><button class="sm" id="none">Aucune</button></div><div id="list"></div></div>`);
    if (!comps.length) card.querySelector("#list").appendChild(el(`<p class="mut">Aucun match dans ce périmètre.</p>`));
    comps.forEach(c => {
      const l = el(`<label class="ck"><input type="checkbox" ${S.compsOn.has(c.id) ? 'checked' : ''}><span style="flex:1">${esc(c.comp)}${c.followed ? ' <span class="badge">suivi</span>' : ''}</span><span class="mut">${c.n} · ${hm(c.first)}</span></label>`);
      l.querySelector("input").onchange = e => { e.target.checked ? S.compsOn.add(c.id) : S.compsOn.delete(c.id); S.prefs.favComps = [...S.compsOn]; savePrefs(); };
      card.querySelector("#list").appendChild(l);
    });
    m.appendChild(card);
    $("#all").onclick = () => { comps.forEach(c => S.compsOn.add(c.id)); S.prefs.favComps = [...S.compsOn]; savePrefs(); render(2); };
    $("#none").onclick = () => { S.compsOn.clear(); render(2); };
    nav(m, 1, 3, () => S.compsOn.size ? true : (toast("Coche au moins une compétition"), false));
  }
  if (step === 3) {
    const p = S.prefs; const spent = spentThisWeek();
    m.appendChild(el(`<div class="card"><h2>Réglages</h2>
      <div class="grid2"><label class="small">Tickets<input type="number" id="nb" min="1" max="10" inputmode="numeric" value="${p.nb}"></label><label class="small">Mise / ticket (€)<input type="number" id="mise" min="1" step="0.5" inputmode="decimal" value="${p.mise}"></label>
      <label class="small">Gain mini (€)<input type="number" id="gmin" min="5" inputmode="numeric" value="${p.gmin}"></label><label class="small">Gain maxi (€)<input type="number" id="gmax" min="10" inputmode="numeric" value="${p.gmax}"></label></div>
      <p class="small" style="margin:10px 0 6px">Style</p><div class="row" id="styles">${Object.entries(STYLE_LABELS).map(([k, l]) => `<span class="chip ${p.style === k ? 'on' : ''}" data-k="${k}">${l}</span>`).join("")}</div>
      <p class="mut small" id="styleHelp"></p>
      <label class="small" style="margin-top:10px">Plafond de budget hebdomadaire (€, 0 = aucun)<input type="number" id="budget" min="0" step="5" inputmode="numeric" value="${p.budgetHebdo}"></label>
      <p class="mut" id="bk"></p></div>`));
    const help = { melange: "4 à 10 sélections, au moins 4 types de paris différents, cote cible = gain visé / mise.",
      safe: "6 à 12 sélections à cote ≤ 1,80 (favoris, double chance, buts). Le TRJ s'effondre quand même avec le nombre de jambes.",
      risque: "3 à 7 sélections dont outsiders, nuls et doublés.",
      discipline: "2 à 3 sélections, marchés 1N2 / double chance / +−2,5 / les 2 marquent uniquement, cote totale 3 à 8. Les gains mini/maxi ne s'appliquent pas." };
    const upd = () => {
      p.nb = Math.min(10, +$("#nb").value || 5); p.mise = +$("#mise").value || 3; p.gmin = +$("#gmin").value || 200; p.gmax = Math.max(p.gmin + 1, +$("#gmax").value || 2000); p.budgetHebdo = +$("#budget").value || 0; savePrefs();
      const cfg = STYLES[p.style]; const [a, b] = targetRange(cfg);
      $("#styleHelp").textContent = help[p.style];
      $("#bk").textContent = `Bankroll de la soirée ${fmt(p.nb * p.mise)} € · cote cible ${fmt(a)} – ${fmt(b)}` + (p.budgetHebdo ? ` · déjà validé cette semaine : ${fmt(spent)} € / ${fmt(p.budgetHebdo)} €` : "");
    };
    m.querySelectorAll("input").forEach(i => i.oninput = upd);
    m.querySelectorAll("#styles .chip").forEach(c => c.onclick = () => { p.style = c.dataset.k; savePrefs(); m.querySelectorAll("#styles .chip").forEach(x => x.classList.toggle("on", x === c)); upd(); });
    upd(); nav(m, 2, 4);
  }
  if (step === 4) {
    const evs = eventsInScope().filter(e => S.compsOn.has(e.comp_id));
    const card = el(`<div class="card"><h2>Matchs</h2><p class="mut">Décoche ce que tu ne veux pas. ${evs.length} matchs. <span class="badge">value</span> = une sélection dépasse ${S.value.min_value_pct ?? 3} % de valeur vs Pinnacle.</p><div id="list"></div></div>`);
    let lastComp = null;
    evs.forEach(e => {
      if (e.comp !== lastComp) { lastComp = e.comp; card.querySelector("#list").appendChild(el(`<p class="mut" style="margin:10px 0 2px"><b>${esc(e.comp)}</b></p>`)); }
      const legs = S.legsByEvent[e.event_id] || []; const fav = legs.find(l => l.type === "fav"); const val = legs.filter(l => l.isValue).sort((a, b) => b.value - a.value)[0];
      const l = el(`<label class="ck"><input type="checkbox" ${S.evOff.has(e.event_id) ? '' : 'checked'}><span style="flex:1">${esc(e.match)}${val ? ` <span class="badge">value ${esc(val.label)} +${fmt(val.value, 1)} %</span>` : ''}<br><span class="mut small">${hm(e.start_ts)} · ${legs.length} paris${fav ? ' · ' + esc(fav.label) + ' ' + fmt(fav.cote) : ''}</span></span></label>`);
      l.querySelector("input").onchange = ev => ev.target.checked ? S.evOff.delete(e.event_id) : S.evOff.add(e.event_id);
      card.querySelector("#list").appendChild(l);
    });
    m.appendChild(card);
    nav(m, 3, 5, () => { const n = selectedEvents().length; const min = S.prefs.style === "discipline" ? 2 : 3; if (n < min) { toast(`Garde au moins ${min} matchs`); return false; } generateAll(); return true; }, "Générer les tickets →");
  }
  if (step === 5) {
    const now = nowS(); const cap = S.prefs.budgetHebdo || 0; const spent = spentThisWeek();
    if (cap && spent + S.tickets.filter(t => !isValidated(t.key)).reduce((s, t) => s + t.mise, 0) > cap) m.appendChild(el(`<div class="banner warn">Plafond hebdo ${fmt(cap)} € : ${fmt(spent)} € déjà validés cette semaine.</div>`));
    if (!S.tickets.length) m.appendChild(el(`<div class="card bad">Aucun ticket possible dans cette fourchette avec ces matchs. Élargis le périmètre, la fourchette de gains ou change de style.</div>`));
    S.tickets.forEach((t, i) => {
      const done = isValidated(t.key); const late = t.deadline - now < 30 * 60;
      const c = el(`<div class="card ticket ${done ? 'done' : ''}"><div class="row between"><h2 style="margin:0">${esc(t.name)}</h2><label class="small row" style="gap:6px"><input type="checkbox" ${done ? 'checked' : ''} style="width:22px;height:22px;margin:0"> validé</label></div>
        <div class="kpi"><span>Cote <b>${fmt(t.cote)}</b>${t.boost ? ` <span class="ok">+${fmt(t.boost * 100, 0)} %</span>` : ""}</span><span>Gain <b>${fmt(t.gain)} €</b></span><span title="Retour théorique au joueur de ce ticket (produit des TRJ des marchés, bonus Combi inclus)">TRJ <b class="${t.trj < 0.5 ? 'bad' : t.trj < 0.7 ? 'warn' : ''}">${pct(t.trj)}</b></span><span class="${late ? 'bad' : ''}">avant <b>${hm(t.deadline)}</b></span></div>
        <div class="legs"></div>
        <a class="open" href="${t.link}" target="_blank" rel="noopener">Ouvrir dans Parions Sport</a>
        <div class="row" style="margin-top:8px"><button class="sm" data-a="regen">Régénérer</button><button class="sm" data-a="copy">Copier le lien</button></div></div>`);
      t.legs.forEach((l, j) => {
        const e = S.byId[l.ev];
        const d = el(`<div class="leg"><span class="t">${TYPES[l.type]}</span><span class="m">${esc(e.match)}${l.isValue ? ` <span class="badge">value +${fmt(l.value, 1)} %</span>` : ""}<br><span class="mut small">${esc(l.label)} · ${hm(e.start_ts)}</span></span><span class="c">${fmt(l.cote)}</span><span class="x" title="Retirer">✕</span></div>`);
        d.querySelector(".x").onclick = () => dropLeg(i, j); c.querySelector(".legs").appendChild(d);
      });
      c.querySelector("input").onchange = e => { setValidated(t, e.target.checked); c.classList.toggle("done", e.target.checked); if (e.target.checked && cap && spentThisWeek() > cap) toast("Plafond hebdomadaire dépassé"); };
      c.querySelector("[data-a=regen]").onclick = () => regenTicket(i);
      c.querySelector("[data-a=copy]").onclick = () => copy(t.link, "Lien copié");
      m.appendChild(c);
    });
    m.appendChild(el(`<div class="card"><div class="row"><button id="all">Tout régénérer</button><button id="txt">Copier le récap</button><button id="exp">Exporter le journal (${validated.length})</button></div>
      <p class="mut small" style="margin-top:8px">Cotes de l'offre du ${S.offre ? esc(dm(S.offre.offer_created_at)) : "?"} ; celles de l'appli FDJ à l'ouverture du panier font foi. Une sélection par match et par ticket, 12 sélections max. Bonus Combi Boosté : dès 4 sélections à cote ≥ ${fmt(S.offre?.boost?.min_cote ?? 1.2)}. Le TRJ affiché est le retour théorique du ticket : l'espérance reste négative.</p></div>`));
    $("#all").onclick = () => { generateAll(); render(5); };
    $("#txt").onclick = () => copy(recap(), "Récap copié");
    $("#exp").onclick = exportJournal;
    nav(m, 4, null);
  }
  window.scrollTo(0, 0);
}
function nav(m, prev, next, check, label) {
  const n = el(`<div class="nav"><button id="prev">← Retour</button>${next != null ? `<button class="pri" id="next">${label || "Suivant →"}</button>` : ""}</div>`);
  n.querySelector("#prev").onclick = () => render(prev); if (next != null) n.querySelector("#next").onclick = () => { if (!check || check()) render(next); }; m.appendChild(n);
}
load();
