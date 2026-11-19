"use strict";

/* ------------------------------------------------------------------ helpers */
const $ = (sel, el = document) => el.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } },
};

const TYPE_RU = {
  duplicate_invoice: "Дубль счёта",
  payment_allocation: "Распределение платежа",
  fx_conversion: "Курс конвертации",
  period_cutoff: "Отнесение к периоду",
};
const TYPE_HINT = {
  duplicate_invoice: "Тот же счёт проведён второй раз под новым номером",
  payment_allocation: "Поступление не (полностью) применено к счёту, который оно гасит",
  fx_conversion: "Документ в валюте пересчитан по курсу не той даты",
  period_cutoff: "Документ вне отчётного периода проведён внутри него",
};
const DISTRACTOR_RU = {
  split_payment: "Разбитая оплата",
  partial_payment: "Честная частичная оплата",
  recurring: "Повторяющиеся суммы",
  refund: "Двойная оплата и возврат",
  boundary: "Документ у границы периода (UTC)",
  next_period_invoice: "Счёт следующего периода",
  weekend_fx: "Курс в выходной",
  prior_invoice: "Счёт прошлого периода",
};
const TABLE_RU = { invoices: "Счёт", payments: "Платёж", ledger: "Проводка", fx: "Курс" };

const state = {
  presets: [],
  episodes: [],
  src: null,
  data: null,
  ix: null,
  reviewer: store.get("auditgym.reviewer", false),
  tab: "overview",
  f: {},
  page: 0,
};

async function api(path) {
  const res = await fetch(path);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || res.statusText);
  return body;
}

/* ------------------------------------------------------------------ index */
function buildIndex(data) {
  const p = data.public;
  const m = p.manifest;
  const ix = {
    m,
    exp: Object.fromEntries(Object.entries(m.currencies).map(([c, v]) => [c, v.exponent])),
    tzMin: parseTz(m.timezone),
    start: Date.parse(m.period_start),
    end: Date.parse(m.period_end),
    inv: new Map(p.invoices.map((x) => [x.invoice_id, x])),
    pay: new Map(p.payments.map((x) => [x.payment_id, x])),
    row: new Map(p.ledger.map((x) => [x.row_id, x])),
    fx: new Map(p.fx.map((x) => [`${x.date}/${x.source_currency}/${x.target_currency}`, x])),
    rowsByInv: new Map(),
    rowsByPay: new Map(),
    paysByInv: new Map(),
    applied: new Map(),
    affected: new Map(),
    evidence: new Map(),
    issues: data.truth ? data.truth.issues : [],
  };
  for (const r of p.ledger) {
    if (r.payment_id) push(ix.rowsByPay, r.payment_id, r);
    else if (r.invoice_id) push(ix.rowsByInv, r.invoice_id, r);
  }
  for (const pay of p.payments) {
    for (const ref of pay.invoice_refs) {
      push(ix.paysByInv, ref.invoice_id, { pay, applied: ref.applied_minor });
      ix.applied.set(ref.invoice_id, (ix.applied.get(ref.invoice_id) || 0) + ref.applied_minor);
    }
  }
  for (const is of ix.issues) {
    for (const a of is.affected_ids) push(ix.affected, a, is);
    for (const s of is.evidence_sets) for (const e of s) push(ix.evidence, e, is);
  }
  return ix;
}
function push(map, k, v) { if (!map.has(k)) map.set(k, []); map.get(k).push(v); }
function parseTz(s) { const sign = s[0] === "-" ? -1 : 1; return sign * (Number(s.slice(1, 3)) * 60 + Number(s.slice(4, 6))); }

/* ------------------------------------------------------------------ formatting */
function money(minor, ccy) {
  const e = state.ix.exp[ccy] ?? 2;
  const v = minor / 10 ** e;
  return `${v.toLocaleString("ru-RU", { minimumFractionDigits: e, maximumFractionDigits: e })} <span class="faint">${esc(ccy)}</span>`;
}
function localStr(ts) {
  const d = new Date(Date.parse(ts) + state.ix.tzMin * 60000);
  return d.toISOString().slice(0, 16).replace("T", " ");
}
function writtenInCompanyTz(ts) { return ts.endsWith(state.ix.m.timezone); }
function tsCell(ts) {
  const short = ts.slice(0, 16).replace("T", " ");
  if (writtenInCompanyTz(ts)) return `<span class="mono">${esc(short)}</span>`;
  return `<span class="mono">${esc(short)}</span> <span class="chip info" title="Время записано в UTC">UTC</span><span class="ts-local">локально ${esc(localStr(ts))}</span>`;
}
function inPeriod(ts) { const t = Date.parse(ts); return t >= state.ix.start && t < state.ix.end; }
function refLink(ref, label) {
  const shown = label ?? ref.split(":").slice(1).join(":");
  return `<span class="idlink" data-ref="${esc(ref)}">${esc(shown)}</span>`;
}
function nullCell(v, ref) { return v == null ? '<span class="faint">null</span>' : ref ? refLink(ref) : esc(v); }
function hlClass(ref) {
  if (!state.reviewer) return "";
  if (state.ix.affected.has(ref)) return "hl-affected";
  if (state.ix.evidence.has(ref)) return "hl-evidence";
  return "";
}
function typeChip(t) { return `<span class="chip bad" title="${esc(TYPE_HINT[t])}">${esc(TYPE_RU[t] || t)}</span>`; }

/* ------------------------------------------------------------------ routing */
function parseHash() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "open" && parts.length >= 3) return { src: { kind: "open", split: parts[1], name: parts[2] }, tab: parts[3] };
  if (parts[0] === "gen" && parts.length >= 3) return { src: { kind: "gen", preset: parts[1], seed: Number(parts[2]) }, tab: parts[3] };
  return null;
}
function srcHash(src, tab) {
  const base = src.kind === "open" ? `#/open/${src.split}/${src.name}` : `#/gen/${src.preset}/${src.seed}`;
  return tab && tab !== "overview" ? `${base}/${tab}` : base;
}
function sameSrc(a, b) { return a && b && JSON.stringify(a) === JSON.stringify(b); }

async function route() {
  const r = parseHash();
  if (!r) {
    const first = state.episodes[0];
    if (first) location.replace(srcHash({ kind: "open", split: first.split, name: first.name }));
    return;
  }
  state.tab = r.tab || "overview";
  if (!sameSrc(r.src, state.src)) {
    state.src = r.src;
    state.f = {};
    state.page = 0;
    await loadEpisode();
  }
  renderAll();
}

async function loadEpisode() {
  $("#view").innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  const s = state.src;
  try {
    state.data = s.kind === "open"
      ? await api(`/api/episodes/${encodeURIComponent(s.split)}/${encodeURIComponent(s.name)}`)
      : await api(`/api/generate?preset=${encodeURIComponent(s.preset)}&seed=${encodeURIComponent(s.seed)}`);
    state.ix = buildIndex(state.data);
  } catch (e) {
    state.data = null;
    state.ix = null;
    $("#company").textContent = "Не удалось загрузить эпизод";
    $("#meta").textContent = e.message;
    $("#view").innerHTML = `<div class="card"><div class="empty">${esc(e.message)}</div></div>`;
  }
  if (s.kind === "gen") {
    $("#gen-preset").value = s.preset;
    $("#gen-seed").value = s.seed;
  }
}

/* ------------------------------------------------------------------ sidebar */
function renderSidebar() {
  const groups = { sample: "Пример", train: "Train", dev: "Dev" };
  let html = "";
  for (const [split, title] of Object.entries(groups)) {
    const eps = state.episodes.filter((e) => e.split === split);
    if (!eps.length) continue;
    html += `<div class="ep-group"><div class="section-title">${title}</div>`;
    for (const e of eps) {
      const active = state.src && state.src.kind === "open" && state.src.split === split && state.src.name === e.name;
      const badge = state.reviewer
        ? e.issues ? `<span class="chip bad">${e.issues}</span>` : '<span class="chip good">чисто</span>'
        : "";
      html += `<a class="ep${active ? " active" : ""}" href="${srcHash({ kind: "open", split, name: e.name })}">
        <span class="ep-name">${esc(e.name)}</span>${badge}
        <span class="ep-sub">${esc(e.company_name)} · ${esc(e.base_currency)} · ${esc(e.period_start.slice(0, 7))} · ${e.counts.ledger_rows} строк</span>
      </a>`;
    }
    html += "</div>";
  }
  $("#episode-list").innerHTML = html;
}

/* ------------------------------------------------------------------ header */
function renderHeader() {
  const ix = state.ix;
  if (!ix) return;
  const m = ix.m;
  const srcLabel = state.src.kind === "open"
    ? `<span class="chip accent">${esc(state.src.split)} / ${esc(state.src.name)}</span>`
    : `<span class="chip accent">сгенерировано · ${esc(state.src.preset)} · seed ${esc(state.src.seed)}</span>`;
  $("#company").textContent = m.company_name;
  $("#meta").innerHTML = `${srcLabel}
    <span>Период <b>${esc(m.period_start.slice(0, 10))} — ${esc(localStr(new Date(ix.end - 1).toISOString()).slice(0, 10))}</b></span>
    <span>Часовой пояс <b>UTC${esc(m.timezone)}</b></span>
    <span>Базовая валюта <b>${esc(m.base_currency)}</b></span>
    <span>Валюты <b>${esc(Object.keys(m.currencies).join(", "))}</b></span>
    <span>Округление <b>${esc(m.rounding.mode.replace("ROUND_", ""))}</b></span>
    <span class="mono faint">${esc(m.episode_id)}</span>`;

  const banner = $("#mode-banner");
  banner.className = "mode-banner" + (state.reviewer ? " reviewer" : "");
  banner.innerHTML = state.reviewer
    ? '<span class="dot"></span><span><b>Режим проверяющего.</b> Видны закрытые файлы оценщика: эталонные ошибки, доказательства и история внесённых изменений. Агент их никогда не видит.</span>'
    : '<span class="dot"></span><span><b>Взгляд агента.</b> Только открытые записи — то же, что получает ИИ-аудитор через инструменты среды. Включите режим проверяющего, чтобы увидеть эталон.</span>';

  const c = m.counts;
  const debit = state.data.public.ledger.reduce((s, r) => s + r.debit_minor, 0);
  const credit = state.data.public.ledger.reduce((s, r) => s + r.credit_minor, 0);
  const issues = ix.issues.length;
  $("#stats").innerHTML = [
    stat("Проводки", c.ledger_rows, "строк в ledger.csv"),
    stat("Счета", c.invoices, `${state.data.public.invoices.filter((i) => ix.rowsByInv.has(i.invoice_id)).length} проведено`),
    stat("Платежи", c.payments, `${state.data.public.payments.filter((p) => p.kind === "refund").length} возвратов`),
    stat("Курсы", c.fx_rates, "только рабочие дни"),
    stat("Дт = Кт", debit === credit ? "✓" : "✗", "двойная запись", debit === credit ? "good" : "bad"),
    state.reviewer
      ? stat("Ошибки в эталоне", issues, issues ? `${new Set(ix.issues.map((i) => i.type)).size} типа · ${new Set(ix.issues.map((i) => i.group).filter(Boolean)).size} сценар.` : "чистая компания", issues ? "bad" : "good")
      : stat("Ошибки в эталоне", "•••", "скрыто от агента"),
  ].join("");
}
function stat(label, value, note, cls = "") {
  return `<div class="stat ${cls}"><div class="stat-label">${esc(label)}</div><div class="stat-value">${esc(value)}</div><div class="stat-note">${esc(note)}</div></div>`;
}

/* ------------------------------------------------------------------ tabs */
function tabs() {
  const p = state.data.public;
  const t = [
    ["overview", "Обзор"],
    ["ledger", "Проводки", p.ledger.length],
    ["invoices", "Счета", p.invoices.length],
    ["payments", "Платежи", p.payments.length],
    ["fx", "Курсы", p.fx.length],
  ];
  if (state.reviewer) {
    t.push(["issues", "Ошибки", state.ix.issues.length, "danger"]);
    t.push(["provenance", "История генерации", null, "danger"]);
  }
  return t;
}
function renderTabs() {
  const list = tabs();
  if (!list.some(([k]) => k === state.tab)) state.tab = "overview";
  $("#tabs").innerHTML = list
    .map(([k, label, n, cls]) => `<button class="tab ${cls || ""}${k === state.tab ? " active" : ""}" data-tab="${k}" role="tab">${label}${n != null ? `<span class="count">${n}</span>` : ""}</button>`)
    .join("");
}

function renderView() {
  const fn = { overview: viewOverview, ledger: viewLedger, invoices: viewInvoices, payments: viewPayments, fx: viewFx, issues: viewIssues, provenance: viewProvenance }[state.tab];
  $("#view").innerHTML = fn();
}

function renderAll() {
  renderSidebar();
  if (!state.ix) return;
  renderHeader();
  renderTabs();
  renderView();
}

/* ------------------------------------------------------------------ overview */
function viewOverview() {
  const p = state.data.public;
  const ix = state.ix;
  const base = ix.m.base_currency;

  const acc = new Map();
  for (const r of p.ledger) {
    const a = acc.get(r.account) || { d: 0, c: 0, n: 0 };
    a.d += r.debit_minor; a.c += r.credit_minor; a.n += 1;
    acc.set(r.account, a);
  }
  const accRows = [...acc.entries()].sort((a, b) => b[1].d + b[1].c - (a[1].d + a[1].c));
  const totD = accRows.reduce((s, [, a]) => s + a.d, 0);
  const totC = accRows.reduce((s, [, a]) => s + a.c, 0);

  const byCcy = new Map();
  for (const i of p.invoices) {
    const x = byCcy.get(i.currency) || { n: 0, sum: 0, booked: 0 };
    x.n += 1; x.sum += i.total_minor; x.booked += ix.rowsByInv.has(i.invoice_id) ? 1 : 0;
    byCcy.set(i.currency, x);
  }

  const pol = p.policy;
  let reviewerCard = "";
  if (state.reviewer && state.data.provenance) {
    const pv = state.data.provenance;
    const counts = {};
    for (const d of pv.distractors) counts[d.kind] = (counts[d.kind] || 0) + 1;
    reviewerCard = `<div class="card"><div class="card-head"><div class="card-title">Что заложено в эпизод</div><span class="chip bad">закрыто</span></div>
      <div class="card-body">
        <div class="kv">
          <div>Ошибки по типам</div><div>${Object.entries(pv.sampled.error_counts).map(([t, n]) => `${esc(TYPE_RU[t])}: <b>${n}</b>`).join("<br>")}</div>
          <div>Сценарии</div><div>A: <b>${pv.sampled.interactions.A}</b> · B: <b>${pv.sampled.interactions.B}</b></div>
          <div>Отвлекающие случаи</div><div>${Object.entries(counts).map(([k, n]) => `${esc(DISTRACTOR_RU[k] || k)}: <b>${n}</b>`).join("<br>") || "—"}</div>
          <div>До внесения ошибок</div><div>${pv.pre_injection.ledger_rows} строк, Дт = Кт: <b>${pv.pre_injection.total_debit_minor === pv.pre_injection.total_credit_minor ? "да" : "нет"}</b>, инварианты: ${esc(pv.pre_injection.invariants)}</div>
          <div>Генератор</div><div class="mono">v${esc(pv.generator_version)} · config v${esc(pv.config_version)} · попытка ${pv.attempt}</div>
        </div>
      </div></div>`;
  }

  return `<div class="grid-2">
    <div class="card"><div class="card-head"><div class="card-title">Активность по дням</div><span class="muted">проводки в поясе UTC${esc(ix.m.timezone)}</span></div>
      <div class="card-body">${dailyChart()}</div></div>
    <div class="card"><div class="card-head"><div class="card-title">Обороты по счетам учёта</div>
      <span class="chip ${totD === totC ? "good" : "bad"}">Дт ${totD === totC ? "=" : "≠"} Кт</span></div>
      <div class="table-wrap" style="max-height:340px"><table><thead><tr><th>Счёт</th><th class="num">Строк</th><th class="num">Дебет</th><th class="num">Кредит</th></tr></thead><tbody>
      ${accRows.map(([a, x]) => `<tr data-filter-account="${esc(a)}"><td class="mono">${esc(a)}</td><td class="num">${x.n}</td><td class="num">${money(x.d, base)}</td><td class="num">${money(x.c, base)}</td></tr>`).join("")}
      <tr><td><b>Итого</b></td><td></td><td class="num"><b>${money(totD, base)}</b></td><td class="num"><b>${money(totC, base)}</b></td></tr>
      </tbody></table></div></div>
    <div class="card"><div class="card-head"><div class="card-title">Счета по валютам</div></div>
      <table><thead><tr><th>Валюта</th><th class="num">Счетов</th><th class="num">Проведено</th><th class="num">Сумма</th></tr></thead><tbody>
      ${[...byCcy.entries()].map(([c, x]) => `<tr><td><b>${esc(c)}</b>${c === base ? ' <span class="chip">базовая</span>' : ""}</td><td class="num">${x.n}</td><td class="num">${x.booked}</td><td class="num">${money(x.sum, c)}</td></tr>`).join("")}
      </tbody></table></div>
    <div class="card"><div class="card-head"><div class="card-title">Учётная политика</div><span class="muted">policy.json</span></div>
      <div class="card-body"><div class="kv">
        <div>Период</div><div>[${esc(pol.period.start)}, ${esc(pol.period.end)})</div>
        <div>Дата документа</div><div>${esc(pol.period.cutoff_basis)}</div>
        <div>Дата курса</div><div>${esc(pol.fx.rate_date)}</div>
        <div>Нет курса</div><div>${esc(pol.fx.missing_rate)}</div>
        <div>Погашение AR</div><div>${esc(pol.fx.settlement)}</div>
        <div>Округление</div><div>${esc(pol.rounding.mode)} — ${esc(pol.rounding.scope)}</div>
      </div></div></div>
    ${reviewerCard}
  </div>`;
}

function dailyChart() {
  const ix = state.ix;
  const days = Math.round((ix.end - ix.start) / 864e5);
  const counts = new Array(days).fill(0);
  for (const r of state.data.public.ledger) {
    const i = Math.floor((Date.parse(r.timestamp) - ix.start) / 864e5);
    if (i >= 0 && i < days) counts[i] += 1;
  }
  const W = 640, H = 170, L = 30, B = 24, T = 8;
  const max = Math.max(1, ...counts);
  const bw = (W - L - 8) / days;
  const bars = counts.map((n, i) => {
    const h = ((H - B - T) * n) / max;
    const d = new Date(ix.start + i * 864e5 + ix.tzMin * 60000);
    const wd = d.getUTCDay();
    return `<rect class="bar${wd === 0 || wd === 6 ? " out" : ""}" x="${L + i * bw + 1}" y="${H - B - h}" width="${Math.max(1, bw - 2)}" height="${h}" rx="2"><title>${d.toISOString().slice(0, 10)}: ${n} строк</title></rect>`;
  }).join("");
  const ticks = [0, Math.floor(days / 2), days - 1].map((i) => {
    const d = new Date(ix.start + i * 864e5 + ix.tzMin * 60000).toISOString().slice(5, 10);
    return `<text x="${L + i * bw + bw / 2}" y="${H - 6}" text-anchor="middle">${d}</text>`;
  }).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Число проводок по дням">
    <line class="grid" x1="${L}" x2="${W}" y1="${T}" y2="${T}"/><text x="${L - 6}" y="${T + 4}" text-anchor="end">${max}</text>
    <line class="axis" x1="${L}" x2="${W}" y1="${H - B}" y2="${H - B}"/>${bars}${ticks}</svg>
    <div class="legend" style="margin-top:6px"><span class="muted">Серым — выходные</span></div>`;
}

/* ------------------------------------------------------------------ tables */
function filterInput(key, placeholder) {
  return `<input class="search" data-f="${key}" placeholder="${esc(placeholder)}" value="${esc(state.f[key] || "")}">`;
}
function filterSelect(key, options, label) {
  return `<select data-f="${key}" aria-label="${esc(label)}"><option value="">${esc(label)}: все</option>${options
    .map(([v, t]) => `<option value="${esc(v)}"${state.f[key] === v ? " selected" : ""}>${esc(t)}</option>`)
    .join("")}</select>`;
}
function legend() {
  return state.reviewer ? '<div class="legend"><span class="l-aff">затронуто ошибкой</span><span class="l-ev">доказательство</span></div>' : "";
}
function paged(rows, renderRow, cols, empty) {
  const size = 100;
  const pages = Math.max(1, Math.ceil(rows.length / size));
  if (state.page >= pages) state.page = pages - 1;
  const slice = rows.slice(state.page * size, state.page * size + size);
  const body = slice.length ? slice.map(renderRow).join("") : `<tr><td colspan="${cols}"><div class="empty">${empty}</div></td></tr>`;
  const pager = pages > 1
    ? `<div class="pager"><span>${state.page * size + 1}–${Math.min(rows.length, (state.page + 1) * size)} из ${rows.length}</span>
       <span><button class="btn" data-page="-1"${state.page === 0 ? " disabled" : ""}>←</button> <button class="btn" data-page="1"${state.page >= pages - 1 ? " disabled" : ""}>→</button></span></div>`
    : `<div class="pager"><span>${rows.length} записей</span></div>`;
  return { body, pager };
}
function matches(obj, q) {
  if (!q) return true;
  return JSON.stringify(obj).toLowerCase().includes(q.toLowerCase());
}

function viewLedger() {
  const p = state.data.public;
  const base = state.ix.m.base_currency;
  const accounts = [...new Set(p.ledger.map((r) => r.account))].sort();
  const f = state.f;
  let rows = p.ledger.filter((r) => matches(r, f.q));
  if (f.account) rows = rows.filter((r) => r.account === f.account);
  if (f.kind === "doc") rows = rows.filter((r) => r.invoice_id || r.payment_id);
  if (f.kind === "bg") rows = rows.filter((r) => !r.invoice_id && !r.payment_id);
  if (f.kind === "hl" && state.reviewer) rows = rows.filter((r) => hlClass(`ledger:${r.row_id}`));
  const kinds = [["doc", "с документом"], ["bg", "фоновые"]];
  if (state.reviewer) kinds.push(["hl", "только помеченные"]);
  const { body, pager } = paged(rows, (r) => `<tr class="${hlClass(`ledger:${r.row_id}`)}" data-ref="ledger:${esc(r.row_id)}">
      <td class="mono">${esc(r.row_id)}</td><td>${tsCell(r.timestamp)}</td><td class="mono">${esc(r.account)}</td>
      <td class="num">${r.debit_minor ? money(r.debit_minor, base) : ""}</td><td class="num">${r.credit_minor ? money(r.credit_minor, base) : ""}</td>
      <td>${nullCell(r.entity_id)}</td><td>${nullCell(r.invoice_id, r.invoice_id && `invoices:${r.invoice_id}`)}</td><td>${nullCell(r.payment_id, r.payment_id && `payments:${r.payment_id}`)}</td></tr>`, 8, "Ничего не найдено");
  return `<div class="card"><div class="card-head"><div class="toolbar">${filterInput("q", "Поиск: ID, счёт, сумма…")}${filterSelect("account", accounts.map((a) => [a, a]), "Счёт")}${filterSelect("kind", kinds, "Строки")}</div>${legend()}</div>
    <div class="table-wrap"><table><thead><tr><th>row_id</th><th>Время</th><th>Счёт учёта</th><th class="num">Дебет</th><th class="num">Кредит</th><th>entity</th><th>invoice</th><th>payment</th></tr></thead><tbody>${body}</tbody></table></div>${pager}</div>`;
}

function viewInvoices() {
  const p = state.data.public;
  const ix = state.ix;
  const f = state.f;
  let rows = p.invoices.filter((i) => matches(i, f.q));
  if (f.ccy) rows = rows.filter((i) => i.currency === f.ccy);
  if (f.booked === "yes") rows = rows.filter((i) => ix.rowsByInv.has(i.invoice_id));
  if (f.booked === "no") rows = rows.filter((i) => !ix.rowsByInv.has(i.invoice_id));
  rows = [...rows].sort((a, b) => Date.parse(a.issued_at) - Date.parse(b.issued_at));
  const { body, pager } = paged(rows, (i) => {
    const booked = ix.rowsByInv.has(i.invoice_id);
    const open = i.total_minor - (ix.applied.get(i.invoice_id) || 0);
    return `<tr class="${hlClass(`invoices:${i.invoice_id}`)}" data-ref="invoices:${esc(i.invoice_id)}">
      <td class="mono">${esc(i.invoice_id)}</td><td>${tsCell(i.issued_at)}</td><td class="mono">${esc(i.entity_id)}</td>
      <td class="num">${money(i.total_minor, i.currency)}</td><td class="num">${open ? money(open, i.currency) : '<span class="chip good">оплачен</span>'}</td>
      <td>${i.line_items.length}</td>
      <td>${booked ? '<span class="chip accent">проведён</span>' : '<span class="chip">не проведён</span>'}${inPeriod(i.issued_at) ? "" : ' <span class="chip warn">вне периода</span>'}</td></tr>`;
  }, 7, "Нет счетов");
  const ccys = Object.keys(ix.m.currencies).map((c) => [c, c]);
  return `<div class="card"><div class="card-head"><div class="toolbar">${filterInput("q", "Поиск: номер, клиент, позиция…")}${filterSelect("ccy", ccys, "Валюта")}${filterSelect("booked", [["yes", "проведён"], ["no", "не проведён"]], "Учёт")}</div>${legend()}</div>
    <div class="table-wrap"><table><thead><tr><th>invoice_id</th><th>Выставлен</th><th>Клиент</th><th class="num">Сумма</th><th class="num">Открыто</th><th>Строк</th><th>Статус</th></tr></thead><tbody>${body}</tbody></table></div>${pager}</div>`;
}

function viewPayments() {
  const p = state.data.public;
  const ix = state.ix;
  const f = state.f;
  let rows = p.payments.filter((x) => matches(x, f.q));
  if (f.kind) rows = rows.filter((x) => x.kind === f.kind);
  if (f.alloc === "full") rows = rows.filter((x) => x.kind === "receipt" && unapplied(x) === 0);
  if (f.alloc === "rest") rows = rows.filter((x) => x.kind === "receipt" && unapplied(x) > 0);
  rows = [...rows].sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
  const { body, pager } = paged(rows, (x) => {
    const ua = x.kind === "receipt" ? unapplied(x) : 0;
    const refs = x.invoice_refs.map((r) => refLink(`invoices:${r.invoice_id}`)).join(", ") || '<span class="faint">—</span>';
    return `<tr class="${hlClass(`payments:${x.payment_id}`)}" data-ref="payments:${esc(x.payment_id)}">
      <td class="mono">${esc(x.payment_id)}</td><td>${tsCell(x.timestamp)}</td><td class="mono">${esc(x.entity_id)}</td>
      <td class="num">${money(x.amount_minor, x.currency)}</td><td>${refs}</td>
      <td class="num">${ua ? money(ua, x.currency) : ""}</td>
      <td>${x.kind === "refund" ? '<span class="chip warn">возврат</span>' : '<span class="chip">поступление</span>'}${ix.rowsByPay.has(x.payment_id) ? "" : ' <span class="chip">не проведён</span>'}</td></tr>`;
  }, 7, "Нет платежей");
  return `<div class="card"><div class="card-head"><div class="toolbar">${filterInput("q", "Поиск: номер, клиент, счёт…")}${filterSelect("kind", [["receipt", "поступления"], ["refund", "возвраты"]], "Тип")}${filterSelect("alloc", [["full", "полностью распределены"], ["rest", "есть остаток"]], "Распределение")}</div>${legend()}</div>
    <div class="table-wrap"><table><thead><tr><th>payment_id</th><th>Время</th><th>Клиент</th><th class="num">Сумма</th><th>Применён к</th><th class="num">Не распределено</th><th>Тип</th></tr></thead><tbody>${body}</tbody></table></div>${pager}</div>`;
}
function unapplied(x) { return x.amount_minor - x.invoice_refs.reduce((s, r) => s + r.applied_minor, 0); }

function viewFx() {
  const p = state.data.public;
  const ix = state.ix;
  if (!p.fx.length) return '<div class="card"><div class="empty">Компания работает в одной валюте — курсов нет.</div></div>';
  const by = new Map();
  for (const r of p.fx) push(by, r.source_currency, r);
  const charts = [...by.entries()].map(([ccy, rows]) => `<div class="card"><div class="card-head"><div class="card-title">${esc(ccy)} → ${esc(ix.m.base_currency)}</div><span class="muted">${rows.length} курсов · затенён отчётный период</span></div><div class="card-body">${fxChart(rows)}</div></div>`).join("");
  let rows = p.fx.filter((r) => matches(r, state.f.q));
  const { body, pager } = paged(rows, (r) => {
    const ref = `fx:${r.date}/${r.source_currency}/${r.target_currency}`;
    return `<tr class="${hlClass(ref)}" data-ref="${esc(ref)}"><td class="mono">${esc(r.date)}</td><td>${esc(r.source_currency)}</td><td>${esc(r.target_currency)}</td><td class="num">${esc(r.rate)}</td></tr>`;
  }, 4, "Нет курсов");
  return `<div class="grid-2" style="margin-bottom:16px">${charts}</div>
    <div class="card"><div class="card-head"><div class="toolbar">${filterInput("q", "Поиск: дата, валюта…")}</div>${legend()}</div>
    <div class="table-wrap"><table><thead><tr><th>Дата</th><th>Из</th><th>В</th><th class="num">Курс</th></tr></thead><tbody>${body}</tbody></table></div>${pager}</div>`;
}
function fxChart(rows) {
  const ix = state.ix;
  const W = 640, H = 190, L = 64, R = 10, T = 10, B = 24;
  const xs = rows.map((r) => Date.parse(r.date + "T12:00:00Z"));
  const ys = rows.map((r) => Number(r.rate));
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = (y1 - y0) * 0.1 || y0 * 0.01;
  const X = (t) => L + ((t - x0) / (x1 - x0 || 1)) * (W - L - R);
  const Y = (v) => T + (1 - (v - (y0 - pad)) / (y1 - y0 + 2 * pad)) * (H - T - B);
  const path = xs.map((t, i) => `${i ? "L" : "M"}${X(t).toFixed(1)} ${Y(ys[i]).toFixed(1)}`).join(" ");
  const ps = Math.max(L, X(ix.start)), pe = Math.min(W - R, X(ix.end));
  const fmtV = (v) => v.toLocaleString("ru-RU", { maximumSignificantDigits: 6 });
  const dots = state.reviewer
    ? rows.map((r, i) => (ix.evidence.has(`fx:${r.date}/${r.source_currency}/${r.target_currency}`) ? `<circle cx="${X(xs[i])}" cy="${Y(ys[i])}" r="4" fill="var(--warn)"><title>Доказательство: ${r.date}</title></circle>` : "")).join("")
    : "";
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Динамика курса">
    <rect x="${ps}" y="${T}" width="${Math.max(0, pe - ps)}" height="${H - T - B}" fill="var(--accent-soft)"/>
    <line class="grid" x1="${L}" x2="${W - R}" y1="${Y(y1)}" y2="${Y(y1)}"/><line class="grid" x1="${L}" x2="${W - R}" y1="${Y(y0)}" y2="${Y(y0)}"/>
    <text x="${L - 6}" y="${Y(y1) + 4}" text-anchor="end">${fmtV(y1)}</text><text x="${L - 6}" y="${Y(y0) + 4}" text-anchor="end">${fmtV(y0)}</text>
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>${dots}
    <text x="${L}" y="${H - 6}">${rows[0].date}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${rows[rows.length - 1].date}</text></svg>`;
}

/* ------------------------------------------------------------------ reviewer views */
function viewIssues() {
  const ix = state.ix;
  if (!ix.issues.length) {
    return `<div class="card"><div class="empty"><div style="font-size:28px">✓</div><b>Чистая компания</b><br>В эталоне нет ни одной ошибки. Правильный ответ агента — пустой список выводов; любое обвинение снизит награду.</div></div>`;
  }
  const pv = state.data.provenance;
  return `<div class="issues">${ix.issues.map((is) => {
    const changes = (pv?.changes || []).filter((c) => c.issue_ids.includes(is.issue_id));
    const diffs = is.affected_ids.map((a) => pv?.ledger_diff?.[a] && diffBlock(a, pv.ledger_diff[a])).filter(Boolean).join("");
    return `<article class="issue" id="${esc(is.issue_id)}">
      <div class="issue-head"><span class="mono faint">${esc(is.issue_id)}</span>${typeChip(is.type)}${is.group ? `<span class="chip accent" title="Взаимодействующий сценарий">сценарий ${esc(is.group)}</span>` : ""}
        <span class="issue-amount">${money(is.expected_amount_minor, is.currency)}</span></div>
      <p class="issue-desc">${esc(is.description)}</p>
      <div class="kv">
        <div>Затронуто</div><div>${is.affected_ids.map((a) => refLink(a, a)).join(", ")}</div>
        <div>Доказательства</div><div>${is.evidence_sets.map((s) => `<span class="evidence-set">${s.map((e) => refLink(e, e)).join(" ")}</span>`).join("")}</div>
        <div>Допуск по сумме</div><div>${is.tolerance_minor} мин. ед.</div>
        ${changes.length ? `<div>Внесённые изменения</div><div>${changes.map(changeLine).join("<br>")}</div>` : ""}
      </div>${diffs}</article>`;
  }).join("")}</div>`;
}
function changeLine(c) {
  const show = (v) => (v === null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));
  return `${refLink(c.target, c.target)} <span class="mono">${esc(c.field)}</span>: <span class="mono faint">${esc(show(c.before))}</span> → <span class="mono">${esc(show(c.after))}</span>${c.note ? ` <span class="chip">${esc(c.note)}</span>` : ""}`;
}
function diffBlock(key, d) {
  const fmt = (rows) => (rows ? rows.map((r) => `${r.account.padEnd(22)} Дт ${String(r.debit_minor).padStart(12)}  Кт ${String(r.credit_minor).padStart(12)}`).join("\n") : "(проводки не было)");
  return `<div class="diff"><div><h4>Проводка ${esc(key)} — до</h4><pre class="before">${esc(fmt(d.before))}</pre></div><div><h4>после внесения ошибки</h4><pre class="after">${esc(fmt(d.after))}</pre></div></div>`;
}
function viewProvenance() {
  const pv = state.data.provenance;
  if (!pv) return '<div class="card"><div class="empty">Нет данных</div></div>';
  const dis = pv.distractors.map((d) => `<tr><td>${esc(DISTRACTOR_RU[d.kind] || d.kind)}</td><td>${d.ids.map((i) => refLink(i, i)).join(", ")}</td></tr>`).join("");
  return `<div class="grid-2">
    <div class="card"><div class="card-head"><div class="card-title">Корректные отвлекающие случаи</div><span class="chip good">не ошибки</span></div>
      <div class="table-wrap" style="max-height:480px"><table><thead><tr><th>Вид</th><th>Записи</th></tr></thead><tbody>${dis || '<tr><td colspan="2"><div class="empty">—</div></td></tr>'}</tbody></table></div></div>
    <div class="card"><div class="card-head"><div class="card-title">Журнал внесённых изменений</div><span class="muted">provenance.changes</span></div>
      <div class="card-body">${pv.changes.length ? pv.changes.map((c) => `<div style="margin-bottom:8px"><span class="mono faint">${esc(c.issue_ids.join(", "))}</span> ${changeLine(c)}</div>`).join("") : '<span class="muted">Изменений нет — чистая компания.</span>'}</div></div>
    <div class="card"><div class="card-head"><div class="card-title">Конфигурация</div><span class="muted">seed скрыт от агента</span></div>
      <div class="card-body"><pre class="mono" style="margin:0;white-space:pre-wrap">${esc(JSON.stringify({ seed: pv.seed, config: pv.config, company: pv.company }, null, 2))}</pre></div></div>
  </div>`;
}

/* ------------------------------------------------------------------ drawer */
function openRecord(ref) {
  const ix = state.ix;
  const [table, ...rest] = ref.split(":");
  const id = rest.join(":");
  let html = "";
  if (table === "invoices" && ix.inv.has(id)) html = drawerInvoice(ix.inv.get(id));
  else if (table === "payments" && ix.pay.has(id)) html = drawerPayment(ix.pay.get(id));
  else if (table === "ledger" && ix.row.has(id)) html = drawerRow(ix.row.get(id));
  else if (table === "fx" && ix.fx.has(id)) html = drawerFx(ix.fx.get(id));
  else html = `<div class="empty">Запись ${esc(ref)} не найдена</div>`;
  $("#drawer-title").innerHTML = `<div class="kind">${esc(TABLE_RU[table] || table)}</div><div class="rid">${esc(id)}</div>`;
  $("#drawer-body").innerHTML = issuesFor(ref) + html;
  $("#drawer").classList.add("open");
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#scrim").classList.add("open");
  $("#drawer-body").scrollTop = 0;
}
function closeDrawer() {
  $("#drawer").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#scrim").classList.remove("open");
}
function issuesFor(ref) {
  if (!state.reviewer) return "";
  const aff = state.ix.affected.get(ref) || [];
  const ev = (state.ix.evidence.get(ref) || []).filter((i) => !aff.includes(i));
  if (!aff.length && !ev.length) return "";
  const line = (i, role) => `<div>${typeChip(i.type)} <span class="mono">${esc(i.issue_id)}</span> · ${role} · ${money(i.expected_amount_minor, i.currency)}</div>`;
  return `<div class="callout">${aff.map((i) => line(i, "затронуто")).join("")}${ev.map((i) => line(i, "доказательство")).join("")}</div>`;
}
function kv(pairs) { return `<div class="kv">${pairs.map(([k, v]) => `<div>${esc(k)}</div><div>${v}</div>`).join("")}</div>`; }
function ledgerTable(rows) {
  if (!rows || !rows.length) return '<p class="muted">Проводок нет — документ не проведён в этом периоде.</p>';
  const base = state.ix.m.base_currency;
  return `<table><thead><tr><th>row_id</th><th>Счёт</th><th class="num">Дебет</th><th class="num">Кредит</th></tr></thead><tbody>${rows
    .map((r) => `<tr class="${hlClass(`ledger:${r.row_id}`)}" data-ref="ledger:${esc(r.row_id)}"><td class="mono">${esc(r.row_id)}</td><td class="mono">${esc(r.account)}</td><td class="num">${r.debit_minor ? money(r.debit_minor, base) : ""}</td><td class="num">${r.credit_minor ? money(r.credit_minor, base) : ""}</td></tr>`)
    .join("")}</tbody></table>`;
}
function drawerInvoice(i) {
  const ix = state.ix;
  const pays = ix.paysByInv.get(i.invoice_id) || [];
  const open = i.total_minor - (ix.applied.get(i.invoice_id) || 0);
  const rows = ix.rowsByInv.get(i.invoice_id);
  return `<section>${kv([
    ["doc_id", `<span class="mono">${esc(i.doc_id)}</span>`],
    ["Клиент", `<span class="mono">${esc(i.entity_id)}</span>`],
    ["Выставлен", tsCell(i.issued_at) + (inPeriod(i.issued_at) ? "" : ' <span class="chip warn">вне периода</span>')],
    ["Срок оплаты", tsCell(i.due_at)],
    ["Сумма", money(i.total_minor, i.currency)],
    ["Открытый остаток", money(open, i.currency)],
  ])}</section>
  <section><h3>Позиции</h3><table><thead><tr><th>Описание</th><th class="num">Кол-во</th><th class="num">Цена</th><th class="num">Сумма</th></tr></thead><tbody>${i.line_items
    .map((li) => `<tr><td>${esc(li.description)}</td><td class="num">${li.quantity}</td><td class="num">${money(li.unit_price_minor, i.currency)}</td><td class="num">${money(li.amount_minor, i.currency)}</td></tr>`)
    .join("")}</tbody></table></section>
  <section><h3>Оплаты</h3>${pays.length ? `<table><tbody>${pays.map(({ pay, applied }) => `<tr data-ref="payments:${esc(pay.payment_id)}"><td>${refLink(`payments:${pay.payment_id}`)}</td><td>${tsCell(pay.timestamp)}</td><td class="num">${money(applied, i.currency)}</td></tr>`).join("")}</tbody></table>` : '<p class="muted">Платежей, применённых к счёту, нет.</p>'}</section>
  <section><h3>Проводка счёта</h3>${ledgerTable(rows)}</section>`;
}
function drawerPayment(x) {
  const ix = state.ix;
  const ua = x.kind === "receipt" ? unapplied(x) : 0;
  return `<section>${kv([
    ["doc_id", `<span class="mono">${esc(x.doc_id)}</span>`],
    ["Клиент", `<span class="mono">${esc(x.entity_id)}</span>`],
    ["Время", tsCell(x.timestamp) + (inPeriod(x.timestamp) ? "" : ' <span class="chip warn">вне периода</span>')],
    ["Тип", x.kind === "refund" ? "возврат" : "поступление"],
    ["Сумма", money(x.amount_minor, x.currency)],
    ["Не распределено", ua ? money(ua, x.currency) : "—"],
    ["Возврат платежа", x.refund_of ? refLink(`payments:${x.refund_of}`) : '<span class="faint">null</span>'],
  ])}</section>
  <section><h3>Применён к счетам</h3>${x.invoice_refs.length ? `<table><tbody>${x.invoice_refs.map((r) => {
    const inv = ix.inv.get(r.invoice_id);
    return `<tr data-ref="invoices:${esc(r.invoice_id)}"><td>${refLink(`invoices:${r.invoice_id}`)}</td><td class="num">${money(r.applied_minor, x.currency)}</td><td class="num faint">из ${inv ? money(inv.total_minor, inv.currency) : "?"}</td></tr>`;
  }).join("")}</tbody></table>` : '<p class="muted">invoice_refs пуст — платёж ни к чему не применён.</p>'}</section>
  <section><h3>Проводка платежа</h3>${ledgerTable(ix.rowsByPay.get(x.payment_id))}</section>`;
}
function drawerRow(r) {
  const ix = state.ix;
  const base = ix.m.base_currency;
  let siblings = [];
  if (r.payment_id) siblings = ix.rowsByPay.get(r.payment_id);
  else if (r.invoice_id) siblings = ix.rowsByInv.get(r.invoice_id);
  else siblings = state.data.public.ledger.filter((x) => x.timestamp === r.timestamp && !x.invoice_id && !x.payment_id);
  return `<section>${kv([
    ["Время", tsCell(r.timestamp)],
    ["Счёт учёта", `<span class="mono">${esc(r.account)}</span>`],
    ["Дебет", r.debit_minor ? money(r.debit_minor, base) : "—"],
    ["Кредит", r.credit_minor ? money(r.credit_minor, base) : "—"],
    ["Клиент", nullCell(r.entity_id)],
    ["Счёт", nullCell(r.invoice_id, r.invoice_id && `invoices:${r.invoice_id}`)],
    ["Платёж", nullCell(r.payment_id, r.payment_id && `payments:${r.payment_id}`)],
  ])}</section>
  <section><h3>Вся проводка</h3>${ledgerTable(siblings)}</section>`;
}
function drawerFx(r) {
  const same = state.data.public.fx.filter((x) => x.source_currency === r.source_currency);
  const i = same.indexOf(r);
  const near = same.slice(Math.max(0, i - 3), i + 4);
  return `<section>${kv([["Дата", `<span class="mono">${esc(r.date)}</span>`], ["Пара", `${esc(r.source_currency)} → ${esc(r.target_currency)}`], ["Курс", `<span class="mono">${esc(r.rate)}</span>`]])}</section>
  <section><h3>Соседние курсы</h3><table><tbody>${near.map((x) => {
    const ref = `fx:${x.date}/${x.source_currency}/${x.target_currency}`;
    return `<tr class="${x === r ? "hl-evidence" : hlClass(ref)}" data-ref="${esc(ref)}"><td class="mono">${esc(x.date)}</td><td class="num">${esc(x.rate)}</td></tr>`;
  }).join("")}</tbody></table><p class="faint">Курсов на выходные нет: по политике берётся последний опубликованный.</p></section>`;
}

/* ------------------------------------------------------------------ events */
function setTab(tab) {
  state.tab = tab;
  state.f = {};
  state.page = 0;
  history.replaceState(null, "", srcHash(state.src, tab));
  renderTabs();
  renderView();
}

document.addEventListener("click", (ev) => {
  const t = ev.target;
  const link = t.closest(".idlink");
  if (link) { ev.stopPropagation(); openRecord(link.dataset.ref); return; }
  const tab = t.closest("[data-tab]");
  if (tab) { setTab(tab.dataset.tab); return; }
  const pageBtn = t.closest("[data-page]");
  if (pageBtn) { state.page += Number(pageBtn.dataset.page); renderView(); return; }
  const acc = t.closest("[data-filter-account]");
  if (acc) { setTab("ledger"); state.f.account = acc.dataset.filterAccount; renderView(); return; }
  const row = t.closest("tr[data-ref]");
  if (row) { openRecord(row.dataset.ref); return; }
  if (t.closest(".ep") && window.innerWidth <= 900) $("#sidebar").classList.remove("open");
});

let searchTimer;
document.addEventListener("input", (ev) => {
  const el = ev.target;
  if (!el.dataset.f) return;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.f[el.dataset.f] = el.value;
    state.page = 0;
    const pos = el.selectionStart;
    renderView();
    const again = document.querySelector(`[data-f="${el.dataset.f}"]`);
    if (again && again.tagName === "INPUT") { again.focus(); again.setSelectionRange(pos, pos); }
  }, el.tagName === "SELECT" ? 0 : 180);
});

$("#reviewer").addEventListener("change", (ev) => {
  state.reviewer = ev.target.checked;
  store.set("auditgym.reviewer", state.reviewer);
  closeDrawer();
  renderAll();
});
$("#drawer-close").addEventListener("click", closeDrawer);
$("#scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeDrawer(); });
$("#menu-btn").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
$("#gen-dice").addEventListener("click", () => { $("#gen-seed").value = Math.floor(Math.random() * 1e6); });
$("#gen-go").addEventListener("click", () => {
  const seed = Number($("#gen-seed").value);
  if (!Number.isInteger(seed) || seed < 0 || seed > 1e9) { $("#gen-seed").focus(); return; }
  location.hash = srcHash({ kind: "gen", preset: $("#gen-preset").value, seed });
});
$("#theme-btn").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  store.set("auditgym.theme", next);
});
window.addEventListener("hashchange", route);

/* ------------------------------------------------------------------ boot */
(async function boot() {
  const theme = store.get("auditgym.theme", window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = theme;
  const review = new URLSearchParams(location.search).get("review");
  if (review === "1" || review === "0") state.reviewer = review === "1";
  $("#reviewer").checked = state.reviewer;
  try {
    const [pr, eps] = await Promise.all([api("/api/presets"), api("/api/episodes")]);
    state.presets = pr.presets;
    state.episodes = eps.episodes;
    $("#gen-preset").innerHTML = pr.presets.map((p) => `<option value="${esc(p)}"${p === "interactions" ? " selected" : ""}>${esc(p)}</option>`).join("");
    $("#side-foot").innerHTML = `Генератор v${esc(pr.generator_version)} · <a href="https://gymnasium.farama.org/api/env/" target="_blank" rel="noopener">Gymnasium API</a><br>Все компании и деньги вымышлены.`;
  } catch (e) {
    $("#company").textContent = "API недоступно";
    $("#meta").textContent = e.message;
    return;
  }
  await route();
})();
