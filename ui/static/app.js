"use strict";

/* ------------------------------------------------------------------ helpers */
const $ = (sel, el = document) => el.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } },
};

/* ------------------------------------------------------------------ human labels */
const TYPE_RU = {
  duplicate_invoice: "Дубль счёта",
  payment_allocation: "Платёж не разнесён",
  fx_conversion: "Неверный курс",
  period_cutoff: "Не тот период",
};
const TYPE_HINT = {
  duplicate_invoice: "Один и тот же счёт покупателю внесён дважды под разными номерами — выручка завышена.",
  payment_allocation: "Деньги от покупателя пришли, но не (полностью) зачтены в оплату счёта, который они гасят.",
  fx_conversion: "Документ в валюте пересчитан в базовую валюту по курсу не той даты.",
  period_cutoff: "Документ относится к другому месяцу, но проведён в этом отчётном периоде.",
};
const GROUP_RU = {
  A: "Связанные ошибки A: частичный валютный платёж на границе месяца",
  B: "Связанные ошибки B: дубль валютного счёта и оплата по неверному курсу",
};
const DISTRACTOR_RU = {
  split_payment: "Счёт оплачен несколькими платежами",
  partial_payment: "Счёт оплачен частично (это нормально)",
  recurring: "Одинаковые суммы каждую неделю",
  refund: "Двойная оплата и возврат денег",
  boundary: "Документ за минуты до/после границы месяца",
  next_period_invoice: "Счёт следующего месяца (верно не проведён)",
  weekend_fx: "Документ в выходной — курс пятницы",
  prior_invoice: "Счёт прошлого месяца",
};
const PRESET_RU = {
  clean_small: "Без ошибок · небольшая компания",
  clean_large: "Без ошибок · крупная компания",
  mixed_small: "Несколько ошибок · небольшая",
  mixed_medium: "Несколько ошибок · средняя",
  mixed_large: "Много ошибок · крупная",
  interactions: "Связанные ошибки (сценарии A и B)",
  single_type: "Повторы одного вида ошибок",
};
const SPLIT_RU = { sample: "Пример", train: "Обучающая", dev: "Проверочная" };
const SPLIT_GROUP_RU = { sample: "Начните отсюда", train: "Обучающие компании", dev: "Проверочные компании" };
const CCY_RU = { KZT: "тенге", USD: "доллар США", EUR: "евро", JPY: "иена" };
const CCY_GEN = { KZT: "тенге", USD: "долларах США", EUR: "евро", JPY: "иенах" };
const MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
const ACCOUNT_RU = {
  accounts_receivable: "Долги покупателей",
  revenue: "Выручка",
  unapplied_cash: "Нераспределённые поступления",
  fx_gain_loss: "Курсовые разницы",
  payroll_tax_payable: "Налоги с зарплаты",
  other_income: "Прочие доходы",
  "expense:rent": "Аренда",
  "expense:payroll": "Зарплата",
  "expense:utilities": "Коммунальные услуги",
  "expense:software": "Программы и подписки",
  "expense:bank_fees": "Банковские комиссии",
  "expense:travel": "Командировки",
  "expense:office": "Офисные расходы",
  "expense:marketing": "Маркетинг",
};
const CHANGE_FIELD_RU = {
  document: "документ",
  "_book.booked": "проведён в учёте",
  "_book.ledger_ts": "дата проводки",
  "_book.rate_date": "дата курса",
  invoice_refs: "разнесение по счетам",
};
const NOTE_RU = {
  missing: "не разнесён",
  partial: "разнесён частично",
  utc_date: "взята дата по UTC, а не местная",
  next_business_day: "взят курс следующего дня",
  stale: "взят устаревший курс",
  due_date: "взят курс на дату срока оплаты",
  early: "документ следующего месяца",
  early_tz: "документ следующего месяца (по UTC выглядит как этот)",
  late: "документ прошлого месяца",
};
const TABLE_RU = { invoices: "Счёт покупателю", payments: "Платёж", ledger: "Строка журнала", fx: "Курс валюты" };

function accName(code) {
  if (code.startsWith("bank:")) return `Банк, счёт в ${CCY_GEN[code.slice(5)] || code.slice(5)}`;
  return ACCOUNT_RU[code] || code;
}
function accCell(code) { return `<span class="acc"><span>${esc(accName(code))}</span><small>${esc(code)}</small></span>`; }
function epLabel(split, name) {
  const n = Number(name.split("_").pop()) + 1;
  return split === "sample" ? "Пример" : `${SPLIT_RU[split] || split} №${n}`;
}
function monthLabel(iso) { return `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`; }
function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}
function roundingRu(mode) { return mode === "ROUND_HALF_EVEN" ? "банковское (к чётному)" : "математическое (половина вверх)"; }
function tzRu(tz) { return `UTC${tz.replace("-", "−")}`; }

const state = {
  presets: [],
  episodes: [],
  src: null,
  data: null,
  ix: null,
  reviewer: store.get("auditgym.reviewer", false),
  introHidden: store.get("auditgym.introHidden", false),
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
function moneyText(minor, ccy) {
  const e = state.ix.exp[ccy] ?? 2;
  return `${(minor / 10 ** e).toLocaleString("ru-RU", { minimumFractionDigits: e, maximumFractionDigits: e })} ${ccy}`;
}
function money(minor, ccy) {
  const e = state.ix.exp[ccy] ?? 2;
  const v = minor / 10 ** e;
  return `${v.toLocaleString("ru-RU", { minimumFractionDigits: e, maximumFractionDigits: e })} <span class="faint">${esc(ccy)}</span>`;
}
function localDate(ts) { return new Date(Date.parse(ts) + state.ix.tzMin * 60000); }
function ruDateTime(ts) {
  const d = localDate(ts).toISOString();
  return `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)} ${d.slice(11, 16)}`;
}
function ruDate(ts) { return ruDateTime(ts).slice(0, 10); }
function isoDateRu(iso) { return `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`; }
function writtenInCompanyTz(ts) { return ts.endsWith(state.ix.m.timezone); }
function tsCell(ts) {
  const local = `<span class="mono">${esc(ruDateTime(ts))}</span>`;
  if (writtenInCompanyTz(ts)) return local;
  return `${local} <span class="chip info" title="В документе время записано по UTC; здесь оно пересчитано в часовой пояс компании">из UTC</span><span class="ts-local">в документе: ${esc(ts.slice(0, 16).replace("T", " "))} UTC</span>`;
}
function inPeriod(ts) { const t = Date.parse(ts); return t >= state.ix.start && t < state.ix.end; }
function refLink(ref, label) {
  const shown = label ?? ref.split(":").slice(1).join(":");
  return `<span class="idlink" data-ref="${esc(ref)}" title="Открыть: ${esc(TABLE_RU[ref.split(":")[0]] || "")}">${esc(shown)}</span>`;
}
function refHuman(ref) {
  const [t, ...rest] = ref.split(":");
  const id = rest.join(":");
  if (t === "fx") { const [d, s, g] = id.split("/"); return refLink(ref, `курс ${s}→${g} на ${isoDateRu(d)}`); }
  if (t === "ledger") return refLink(ref, `строка журнала ${id}`);
  if (t === "invoices") return refLink(ref, `счёт ${id}`);
  if (t === "payments") return refLink(ref, `платёж ${id}`);
  return refLink(ref);
}
function dash(v, ref) { return v == null ? '<span class="faint">—</span>' : ref ? refLink(ref) : esc(v); }
function hlClass(ref) {
  if (!state.reviewer) return "";
  if (state.ix.affected.has(ref)) return "hl-affected";
  if (state.ix.evidence.has(ref)) return "hl-evidence";
  return "";
}
function typeChip(t) { return `<span class="chip bad" title="${esc(TYPE_HINT[t])}">${esc(TYPE_RU[t] || t)}</span>`; }

/* ------------------------------------------------------------------ issue texts */
function docOf(ref) {
  const [t, ...rest] = ref.split(":");
  const id = rest.join(":");
  return t === "invoices" ? `счёт ${id}` : t === "payments" ? `платёж ${id}` : id;
}
function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }
function issueText(is) {
  const amt = moneyText(is.expected_amount_minor, is.currency);
  const aff = is.affected_ids;
  const ev = is.evidence_sets[0] || [];
  if (is.type === "duplicate_invoice") {
    const orig = ev.find((x) => x.startsWith("invoices:") && !aff.includes(x));
    return `${cap(docOf(aff[0]))} — копия счёта ${orig ? orig.slice(9) : "?"}: тот же покупатель, те же позиции и сумма. Копию провели в учёте ещё раз, выручка завышена на ${amt}.`;
  }
  if (is.type === "payment_allocation") {
    const pay = aff.find((x) => x.startsWith("payments:"));
    const inv = aff.find((x) => x.startsWith("invoices:"));
    return `${cap(docOf(pay))} оплачивает ${docOf(inv)}, но ${amt} не зачтены в оплату и лежат на «Нераспределённых поступлениях». Счёт выглядит неоплаченным, хотя деньги пришли.`;
  }
  if (is.type === "fx_conversion") {
    const fx = ev.find((x) => x.startsWith("fx:"));
    const date = fx ? isoDateRu(fx.slice(3, 13)) : "?";
    return `${cap(docOf(aff[0]))} пересчитан в ${CCY_GEN[state.ix.m.base_currency] || state.ix.m.base_currency} по курсу не той даты. По правилам учёта нужен курс на ${date} (местная дата документа). Ошибка в сумме — ${amt}.`;
  }
  if (is.type === "period_cutoff") {
    return `${cap(docOf(aff[0]))} по местному времени компании датирован другим месяцем, но проведён в этом отчётном периоде на ${amt}.`;
  }
  return is.description;
}

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
    $("#company").textContent = "Не удалось загрузить компанию";
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
  let html = "";
  for (const split of ["sample", "train", "dev"]) {
    const eps = state.episodes.filter((e) => e.split === split);
    if (!eps.length) continue;
    html += `<div class="ep-group"><div class="section-title">${SPLIT_GROUP_RU[split]}</div>`;
    for (const e of eps) {
      const active = state.src && state.src.kind === "open" && state.src.split === split && state.src.name === e.name;
      const badge = state.reviewer
        ? e.issues ? `<span class="chip bad" title="Спрятано ошибок">${e.issues} ${plural(e.issues, "ошибка", "ошибки", "ошибок")}</span>` : '<span class="chip good">без ошибок</span>'
        : "";
      html += `<a class="ep${active ? " active" : ""}" href="${srcHash({ kind: "open", split, name: e.name })}">
        <span class="ep-name">${esc(e.company_name)}</span>${badge}
        <span class="ep-sub">${esc(epLabel(split, e.name))} · ${esc(monthLabel(e.period_start))} · ${esc(CCY_RU[e.base_currency] || e.base_currency)} · ${e.counts.ledger_rows} проводок</span>
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
    ? `<span class="chip accent">${esc(epLabel(state.src.split, state.src.name))}</span>`
    : `<span class="chip accent" title="${esc(state.src.preset)}">Создана: ${esc(PRESET_RU[state.src.preset] || state.src.preset)} · вариант ${esc(state.src.seed)}</span>`;
  const others = Object.keys(m.currencies).filter((c) => c !== m.base_currency);
  $("#company").textContent = m.company_name;
  $("#meta").innerHTML = `${srcLabel}
    <span>Отчётный период <b>${esc(monthLabel(m.period_start))}</b> (${esc(isoDateRu(m.period_start))} – ${esc(ruDate(new Date(ix.end - 60000).toISOString()))})</span>
    <span>Часовой пояс компании <b>${esc(tzRu(m.timezone))}</b></span>
    <span>Учёт ведётся в <b>${esc(CCY_GEN[m.base_currency] || m.base_currency)}</b></span>
    ${others.length ? `<span>Документы также в <b>${esc(others.map((c) => CCY_GEN[c] || c).join(", "))}</b></span>` : ""}
    <span title="Как округляются копейки при пересчёте валют">Округление <b>${esc(roundingRu(m.rounding.mode))}</b></span>`;

  const banner = $("#mode-banner");
  banner.className = "mode-banner" + (state.reviewer ? " reviewer" : "");
  banner.innerHTML = state.reviewer
    ? `<span class="dot"></span><span><b>Ответы показаны.</b> Красным отмечены записи с ошибкой, жёлтым — доказательства. ИИ-аудитор этого не видит: он должен найти ошибки сам. ${ix.issues.length ? `<button class="link-btn" data-tab="issues">Список ошибок →</button>` : ""}</span>`
    : '<span class="dot"></span><span><b>Вы видите компанию глазами ИИ-аудитора</b> — только документы и бухгалтерский журнал. Попробуйте найти ошибки сами, потом включите «Показать ответы» справа вверху.</span>';

  const c = m.counts;
  const debit = state.data.public.ledger.reduce((s, r) => s + r.debit_minor, 0);
  const credit = state.data.public.ledger.reduce((s, r) => s + r.credit_minor, 0);
  const issues = ix.issues.length;
  const kinds = new Set(ix.issues.map((i) => i.type)).size;
  const booked = state.data.public.invoices.filter((i) => ix.rowsByInv.has(i.invoice_id)).length;
  $("#stats").innerHTML = [
    stat("Бухгалтерский журнал", c.ledger_rows, `${plural(c.ledger_rows, "строка", "строки", "строк")} проводок`, "", "ledger"),
    stat("Счета покупателям", c.invoices, `${booked} учтено в этом месяце`, "", "invoices"),
    stat("Платежи", c.payments, "поступления и возвраты", "", "payments"),
    stat("Курсы валют", c.fx_rates, "по рабочим дням", "", "fx"),
    stat("Баланс", debit === credit ? "сходится" : "не сходится", "дебет = кредит", debit === credit ? "good small" : "bad small"),
    state.reviewer
      ? stat("Спрятано ошибок", issues, issues ? `${kinds} ${plural(kinds, "вид", "вида", "видов")}` : "компания без ошибок", issues ? "bad" : "good", issues ? "issues" : null)
      : stat("Спрятано ошибок", "?", "включите «Показать ответы»"),
  ].join("");
}
function stat(label, value, note, cls = "", tab = null) {
  return `<div class="stat ${cls}${tab ? " clickable" : ""}"${tab ? ` data-tab="${tab}" title="Открыть"` : ""}><div class="stat-label">${esc(label)}</div><div class="stat-value">${esc(value)}</div><div class="stat-note">${esc(note)}</div></div>`;
}

/* ------------------------------------------------------------------ tabs */
function tabs() {
  const p = state.data.public;
  const t = [
    ["overview", "Обзор"],
    ["ledger", "Журнал проводок", p.ledger.length],
    ["invoices", "Счета покупателям", p.invoices.length],
    ["payments", "Платежи", p.payments.length],
    ["fx", "Курсы валют", p.fx.length],
  ];
  if (state.reviewer) {
    t.push(["issues", "Ошибки (ответы)", state.ix.issues.length, "danger"]);
    t.push(["provenance", "Как создана компания", null, "danger"]);
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
function introBlock() {
  if (state.introHidden) {
    return `<div style="margin-bottom:12px"><button class="link-btn" data-action="intro-show">Как этим пользоваться?</button></div>`;
  }
  return `<section class="intro">
    <h2>Что это такое</h2>
    <p>Это тренажёр для ИИ-аудитора. Перед вами вымышленная компания за один месяц: счета покупателям, платежи, курсы валют и бухгалтерский журнал. В данные спрятаны ошибки. Задача ИИ — найти их и подтвердить доказательствами, а не просто указать на подозрительную строку.</p>
    <div class="steps">
      <div class="step"><span class="n">1</span><div><b>Посмотрите документы</b><span class="muted">Вкладки «Журнал проводок», «Счета покупателям», «Платежи», «Курсы валют».</span></div></div>
      <div class="step"><span class="n">2</span><div><b>Нажмите на любую строку</b><span class="muted">Откроется карточка со связанными документами: счёт, его оплаты, проводки.</span></div></div>
      <div class="step"><span class="n">3</span><div><b>Включите «Показать ответы»</b><span class="muted">Ошибки подсветятся красным, доказательства жёлтым, появится их список с объяснением.</span></div></div>
      <div class="step"><span class="n">4</span><div><b>Создайте новую компанию</b><span class="muted">Слева выберите, что спрятать, и номер варианта — каждый номер даёт свою компанию.</span></div></div>
    </div>
    <h2 style="margin-top:18px">Какие ошибки бывают</h2>
    <div class="types">${Object.keys(TYPE_RU).map((t) => `<div class="type-card"><b>${esc(TYPE_RU[t])}</b>${esc(TYPE_HINT[t])}</div>`).join("")}</div>
    <div class="intro-foot"><span class="muted">Ловушки тоже есть: частичные оплаты, возвраты, одинаковые суммы, время в UTC у границы месяца — всё это корректно и ошибкой не считается.</span><button class="btn ghost" data-action="intro-hide">Понятно, скрыть</button></div>
  </section>`;
}

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

  let reviewerCard = "";
  if (state.reviewer && state.data.provenance) {
    const pv = state.data.provenance;
    const counts = {};
    for (const d of pv.distractors) counts[d.kind] = (counts[d.kind] || 0) + 1;
    const pre = pv.pre_injection;
    reviewerCard = `<div class="card"><div class="card-head"><div class="card-title">Что спрятано в этой компании</div><span class="chip bad">ответы</span></div>
      <div class="card-body">
        <div class="kv">
          <div>Ошибки по видам</div><div>${Object.entries(pv.sampled.error_counts).map(([t, n]) => `${esc(TYPE_RU[t])}: <b>${n}</b>`).join("<br>")}</div>
          <div>Связанные ошибки</div><div>сценарий A: <b>${pv.sampled.interactions.A}</b> · сценарий B: <b>${pv.sampled.interactions.B}</b></div>
          <div>Ловушки (не ошибки)</div><div>${Object.entries(counts).map(([k, n]) => `${esc(DISTRACTOR_RU[k] || k)}: <b>${n}</b>`).join("<br>") || "—"}</div>
          <div>До внесения ошибок</div><div>${pre.ledger_rows} строк, баланс ${pre.total_debit_minor === pre.total_credit_minor ? "<b>сходился</b>" : "<b>не сходился</b>"}, все проверки пройдены</div>
        </div>
      </div></div>`;
  }

  return `${introBlock()}<div class="grid-2">
    <div class="card"><div class="card-head"><div class="card-title">Сколько проводок в день</div><span class="muted">по времени компании</span></div>
      <div class="card-body">${dailyChart()}</div></div>
    <div class="card"><div class="card-head"><div class="card-title">Обороты по счетам учёта</div>
      <span class="chip ${totD === totC ? "good" : "bad"}" title="Сумма всех дебетов равна сумме всех кредитов">${totD === totC ? "баланс сходится" : "баланс не сходится"}</span></div>
      <div class="table-wrap" style="max-height:360px"><table class="compact"><thead><tr><th>Счёт учёта</th><th class="num">Строк</th><th class="num">Дебет, ${esc(base)}</th><th class="num">Кредит, ${esc(base)}</th></tr></thead><tbody>
      ${accRows.map(([a, x]) => `<tr data-filter-account="${esc(a)}" title="Показать строки этого счёта"><td>${accCell(a)}</td><td class="num">${x.n}</td><td class="num">${money(x.d, base)}</td><td class="num">${money(x.c, base)}</td></tr>`).join("")}
      <tr><td><b>Итого</b></td><td></td><td class="num"><b>${money(totD, base)}</b></td><td class="num"><b>${money(totC, base)}</b></td></tr>
      </tbody></table></div></div>
    <div class="card"><div class="card-head"><div class="card-title">Счета покупателям по валютам</div></div>
      <table><thead><tr><th>Валюта</th><th class="num">Счетов</th><th class="num">Учтено в месяце</th><th class="num">Сумма</th></tr></thead><tbody>
      ${[...byCcy.entries()].map(([c, x]) => `<tr data-filter-ccy="${esc(c)}" title="Показать счета в этой валюте"><td><b>${esc(CCY_RU[c] || c)}</b> <span class="faint">${esc(c)}</span>${c === base ? ' <span class="chip">валюта учёта</span>' : ""}</td><td class="num">${x.n}</td><td class="num">${x.booked}</td><td class="num">${money(x.sum, c)}</td></tr>`).join("")}
      </tbody></table></div>
    <div class="card"><div class="card-head"><div class="card-title">Правила учёта компании</div><span class="muted">их знает и ИИ-аудитор</span></div>
      <div class="card-body"><div class="kv">
        <div>Отчётный период</div><div>с ${esc(ruDateTime(ix.m.period_start))} до ${esc(ruDateTime(ix.m.period_end))} (не включая), время компании ${esc(tzRu(ix.m.timezone))}</div>
        <div>Дата документа</div><div>Считается по часовому поясу компании, даже если в документе время записано в UTC</div>
        <div>Курс валюты</div><div>На дату документа; в выходные — последний опубликованный (обычно пятничный)</div>
        <div>Оплата валютного счёта</div><div>Долг покупателя списывается по курсу счёта, разница уходит в «Курсовые разницы»</div>
        <div>Округление</div><div>${esc(roundingRu(ix.m.rounding.mode))}, каждая сумма — до минимальной единицы валюты</div>
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
    return `<rect class="bar${wd === 0 || wd === 6 ? " out" : ""}" x="${L + i * bw + 1}" y="${H - B - h}" width="${Math.max(1, bw - 2)}" height="${h}" rx="2"><title>${isoDateRu(d.toISOString())}: ${n} ${plural(n, "строка", "строки", "строк")}</title></rect>`;
  }).join("");
  const ticks = [0, Math.floor(days / 2), days - 1].map((i) => {
    const d = new Date(ix.start + i * 864e5 + ix.tzMin * 60000).toISOString();
    return `<text x="${L + i * bw + bw / 2}" y="${H - 6}" text-anchor="middle">${d.slice(8, 10)}.${d.slice(5, 7)}</text>`;
  }).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Число проводок по дням">
    <line class="grid" x1="${L}" x2="${W}" y1="${T}" y2="${T}"/><text x="${L - 6}" y="${T + 4}" text-anchor="end">${max}</text>
    <line class="axis" x1="${L}" x2="${W}" y1="${H - B}" y2="${H - B}"/>${bars}${ticks}</svg>
    <div class="legend" style="margin-top:6px"><span class="muted">Фиолетовым — рабочие дни, серым — выходные. Наведите на столбик, чтобы увидеть число.</span></div>`;
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
  return state.reviewer ? '<div class="legend"><span class="l-aff">ошибка</span><span class="l-ev">доказательство</span></div>' : '<span class="muted" style="font-size:12.5px">Нажмите на строку, чтобы открыть подробности</span>';
}
function paged(rows, renderRow, cols, empty) {
  const size = 100;
  const pages = Math.max(1, Math.ceil(rows.length / size));
  if (state.page >= pages) state.page = pages - 1;
  const slice = rows.slice(state.page * size, state.page * size + size);
  const body = slice.length ? slice.map(renderRow).join("") : `<tr><td colspan="${cols}"><div class="empty">${empty}</div></td></tr>`;
  const pager = pages > 1
    ? `<div class="pager"><span>Показаны ${state.page * size + 1}–${Math.min(rows.length, (state.page + 1) * size)} из ${rows.length}</span>
       <span><button class="btn" data-page="-1"${state.page === 0 ? " disabled" : ""}>← Назад</button> <button class="btn" data-page="1"${state.page >= pages - 1 ? " disabled" : ""}>Дальше →</button></span></div>`
    : `<div class="pager"><span>Всего ${rows.length}</span></div>`;
  return { body, pager };
}
function matches(obj, q, extra = "") {
  if (!q) return true;
  return (JSON.stringify(obj) + " " + extra).toLowerCase().includes(q.toLowerCase());
}

function viewLedger() {
  const p = state.data.public;
  const base = state.ix.m.base_currency;
  const accounts = [...new Set(p.ledger.map((r) => r.account))].sort((a, b) => accName(a).localeCompare(accName(b), "ru"));
  const f = state.f;
  let rows = p.ledger.filter((r) => matches(r, f.q, accName(r.account)));
  if (f.account) rows = rows.filter((r) => r.account === f.account);
  if (f.kind === "doc") rows = rows.filter((r) => r.invoice_id || r.payment_id);
  if (f.kind === "bg") rows = rows.filter((r) => !r.invoice_id && !r.payment_id);
  if (f.kind === "hl" && state.reviewer) rows = rows.filter((r) => hlClass(`ledger:${r.row_id}`));
  const kinds = [["doc", "по счетам и платежам"], ["bg", "прочие расходы и доходы"]];
  if (state.reviewer) kinds.push(["hl", "только помеченные"]);
  const { body, pager } = paged(rows, (r) => `<tr class="${hlClass(`ledger:${r.row_id}`)}" data-ref="ledger:${esc(r.row_id)}">
      <td>${tsCell(r.timestamp)}</td><td>${accCell(r.account)}</td>
      <td class="num">${r.debit_minor ? money(r.debit_minor, base) : ""}</td><td class="num">${r.credit_minor ? money(r.credit_minor, base) : ""}</td>
      <td>${r.invoice_id ? refLink(`invoices:${r.invoice_id}`) : r.payment_id ? refLink(`payments:${r.payment_id}`) : '<span class="faint">—</span>'}${r.invoice_id && r.payment_id ? `<span class="cell-sub">платёж ${refLink(`payments:${r.payment_id}`)}</span>` : ""}</td>
      <td>${dash(r.entity_id)}</td><td class="mono faint">${esc(r.row_id)}</td></tr>`, 7, "Ничего не найдено");
  return `<div class="card"><div class="card-head"><div class="toolbar">${filterInput("q", "Поиск: номер, счёт учёта, сумма…")}${filterSelect("account", accounts.map((a) => [a, accName(a)]), "Счёт учёта")}${filterSelect("kind", kinds, "Строки")}</div>${legend()}</div>
    <div class="table-wrap"><table><thead><tr><th>Дата и время</th><th>Счёт учёта</th><th class="num">Дебет</th><th class="num">Кредит</th><th>Документ</th><th>Покупатель</th><th>№ строки</th></tr></thead><tbody>${body}</tbody></table></div>${pager}</div>`;
}

function viewInvoices() {
  const p = state.data.public;
  const ix = state.ix;
  const f = state.f;
  let rows = p.invoices.filter((i) => matches(i, f.q));
  if (f.ccy) rows = rows.filter((i) => i.currency === f.ccy);
  if (f.booked === "yes") rows = rows.filter((i) => ix.rowsByInv.has(i.invoice_id));
  if (f.booked === "no") rows = rows.filter((i) => !ix.rowsByInv.has(i.invoice_id));
  if (f.paid === "paid") rows = rows.filter((i) => i.total_minor - (ix.applied.get(i.invoice_id) || 0) === 0);
  if (f.paid === "open") rows = rows.filter((i) => i.total_minor - (ix.applied.get(i.invoice_id) || 0) > 0);
  rows = [...rows].sort((a, b) => Date.parse(a.issued_at) - Date.parse(b.issued_at));
  const { body, pager } = paged(rows, (i) => {
    const booked = ix.rowsByInv.has(i.invoice_id);
    const paid = ix.applied.get(i.invoice_id) || 0;
    const open = i.total_minor - paid;
    const payState = open === 0 ? '<span class="chip good">оплачен</span>' : paid ? `<span class="chip warn">частично</span><span class="cell-sub">осталось ${money(open, i.currency)}</span>` : '<span class="chip">не оплачен</span>';
    const firstItem = i.line_items[0].description.split(" · ")[0];
    return `<tr class="${hlClass(`invoices:${i.invoice_id}`)}" data-ref="invoices:${esc(i.invoice_id)}">
      <td class="mono">${esc(i.invoice_id)}</td><td>${tsCell(i.issued_at)}</td>
      <td>${esc(firstItem)}${i.line_items.length > 1 ? ` <span class="faint">и ещё ${i.line_items.length - 1}</span>` : ""}<span class="cell-sub">покупатель ${esc(i.entity_id)}</span></td>
      <td class="num">${money(i.total_minor, i.currency)}</td><td>${payState}</td>
      <td>${booked ? '<span class="chip accent">учтён</span>' : inPeriod(i.issued_at) ? '<span class="chip">не учтён</span>' : '<span class="chip">другой месяц</span>'}</td></tr>`;
  }, 6, "Нет счетов");
  const ccys = Object.keys(ix.m.currencies).map((c) => [c, `${CCY_RU[c] || c} (${c})`]);
  return `<div class="card"><div class="card-head"><div class="toolbar">${filterInput("q", "Поиск: номер, покупатель, товар…")}${filterSelect("ccy", ccys, "Валюта")}${filterSelect("paid", [["paid", "оплачен"], ["open", "есть долг"]], "Оплата")}${filterSelect("booked", [["yes", "учтён в журнале"], ["no", "не учтён"]], "Учёт")}</div>${legend()}</div>
    <div class="table-wrap"><table><thead><tr><th>Номер</th><th>Дата счёта</th><th>Что продано</th><th class="num">Сумма</th><th>Оплата</th><th>В журнале</th></tr></thead><tbody>${body}</tbody></table></div>${pager}</div>`;
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
    const refs = x.invoice_refs.map((r) => refLink(`invoices:${r.invoice_id}`)).join(", ");
    const target = x.kind === "refund"
      ? `возврат по платежу ${refLink(`payments:${x.refund_of}`)}`
      : refs || '<span class="chip warn">ни к одному счёту</span>';
    return `<tr class="${hlClass(`payments:${x.payment_id}`)}" data-ref="payments:${esc(x.payment_id)}">
      <td class="mono">${esc(x.payment_id)}</td><td>${tsCell(x.timestamp)}</td>
      <td>${x.kind === "refund" ? '<span class="chip warn">возврат денег</span>' : '<span class="chip">от покупателя</span>'}<span class="cell-sub">покупатель ${esc(x.entity_id)}</span></td>
      <td class="num">${money(x.amount_minor, x.currency)}</td><td>${target}</td>
      <td class="num">${ua ? money(ua, x.currency) : '<span class="faint">—</span>'}</td>
      <td>${ix.rowsByPay.has(x.payment_id) ? '<span class="chip accent">учтён</span>' : '<span class="chip">другой месяц</span>'}</td></tr>`;
  }, 7, "Нет платежей");
  return `<div class="card"><div class="card-head"><div class="toolbar">${filterInput("q", "Поиск: номер, покупатель, счёт…")}${filterSelect("kind", [["receipt", "от покупателей"], ["refund", "возвраты"]], "Тип")}${filterSelect("alloc", [["full", "полностью зачтены"], ["rest", "есть незачтённый остаток"]], "Зачёт")}</div>${legend()}</div>
    <div class="table-wrap"><table><thead><tr><th>Номер</th><th>Дата платежа</th><th>Тип</th><th class="num">Сумма</th><th>В оплату счёта</th><th class="num">Не зачтено</th><th>В журнале</th></tr></thead><tbody>${body}</tbody></table></div>${pager}</div>`;
}
function unapplied(x) { return x.amount_minor - x.invoice_refs.reduce((s, r) => s + r.applied_minor, 0); }

function viewFx() {
  const p = state.data.public;
  const ix = state.ix;
  if (!p.fx.length) return '<div class="card"><div class="empty">Компания работает в одной валюте — курсы не нужны.</div></div>';
  const by = new Map();
  for (const r of p.fx) push(by, r.source_currency, r);
  const charts = [...by.entries()].map(([ccy, rows]) => `<div class="card"><div class="card-head"><div class="card-title">1 ${esc(CCY_RU[ccy] || ccy)} в ${esc(CCY_GEN[ix.m.base_currency] || ix.m.base_currency)}</div><span class="muted">выделен отчётный месяц</span></div><div class="card-body">${fxChart(rows)}</div></div>`).join("");
  const rows = p.fx.filter((r) => matches(r, state.f.q));
  const { body, pager } = paged(rows, (r) => {
    const ref = `fx:${r.date}/${r.source_currency}/${r.target_currency}`;
    return `<tr class="${hlClass(ref)}" data-ref="${esc(ref)}"><td class="mono">${esc(isoDateRu(r.date))}</td><td>1 ${esc(r.source_currency)} =</td><td class="num">${esc(r.rate)} ${esc(r.target_currency)}</td></tr>`;
  }, 3, "Нет курсов");
  return `<div class="grid-2" style="margin-bottom:16px">${charts}</div>
    <div class="card"><div class="card-head"><div class="toolbar">${filterInput("q", "Поиск: дата (2026-03-14), валюта…")}</div>${legend()}</div>
    <div class="table-wrap"><table><thead><tr><th>Дата</th><th>Валюта</th><th class="num">Курс</th></tr></thead><tbody>${body}</tbody></table></div>${pager}</div>`;
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
    ? rows.map((r, i) => (ix.evidence.has(`fx:${r.date}/${r.source_currency}/${r.target_currency}`) ? `<circle cx="${X(xs[i])}" cy="${Y(ys[i])}" r="4" fill="var(--warn)"><title>Доказательство: курс на ${isoDateRu(r.date)}</title></circle>` : "")).join("")
    : "";
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Динамика курса">
    <rect x="${ps}" y="${T}" width="${Math.max(0, pe - ps)}" height="${H - T - B}" fill="var(--accent-soft)"/>
    <line class="grid" x1="${L}" x2="${W - R}" y1="${Y(y1)}" y2="${Y(y1)}"/><line class="grid" x1="${L}" x2="${W - R}" y1="${Y(y0)}" y2="${Y(y0)}"/>
    <text x="${L - 6}" y="${Y(y1) + 4}" text-anchor="end">${fmtV(y1)}</text><text x="${L - 6}" y="${Y(y0) + 4}" text-anchor="end">${fmtV(y0)}</text>
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>${dots}
    <text x="${L}" y="${H - 6}">${isoDateRu(rows[0].date)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${isoDateRu(rows[rows.length - 1].date)}</text></svg>`;
}

/* ------------------------------------------------------------------ reviewer views */
function viewIssues() {
  const ix = state.ix;
  if (!ix.issues.length) {
    return `<div class="card"><div class="empty"><div style="font-size:28px">✓</div><b>В этой компании ошибок нет</b><br>Правильный ответ ИИ-аудитора — «ошибок не найдено». Любое ложное обвинение снизит его оценку.</div></div>`;
  }
  const pv = state.data.provenance;
  const groupsSeen = new Set();
  return `<div class="issues">${ix.issues.map((is, n) => {
    const changes = (pv?.changes || []).filter((c) => c.issue_ids.includes(is.issue_id));
    const diffs = is.affected_ids.map((a) => pv?.ledger_diff?.[a] && diffBlock(pv.ledger_diff[a])).filter(Boolean).join("");
    let groupHead = "";
    if (is.group && !groupsSeen.has(is.group)) {
      groupsSeen.add(is.group);
      groupHead = `<div class="section-title" style="margin:8px 4px 0">${esc(GROUP_RU[is.group[0]] || is.group)}</div>`;
    }
    return `${groupHead}<article class="issue" id="${esc(is.issue_id)}">
      <div class="issue-head"><span class="mono faint">Ошибка ${n + 1}</span>${typeChip(is.type)}${is.group ? `<span class="chip accent" title="${esc(GROUP_RU[is.group[0]] || "")}">связана с другими (${esc(is.group)})</span>` : ""}
        <span class="issue-amount" title="Сумма расхождения">${money(is.expected_amount_minor, is.currency)}</span></div>
      <p class="issue-desc">${esc(issueText(is))}</p>
      <div class="kv">
        <div>Где ошибка</div><div>${is.affected_ids.map(refHuman).join(", ")}</div>
        <div>Чем доказать</div><div>${is.evidence_sets.map((s) => `<span class="evidence-set">${s.map(refHuman).join(" · ")}</span>`).join(" или ")}</div>
        ${changes.length ? `<div>Что изменил генератор</div><div>${changes.map(changeLine).join("<br>")}</div>` : ""}
      </div>${diffs}</article>`;
  }).join("")}</div>`;
}
function changeValue(v) {
  if (v === null || v === undefined) return "—";
  if (v === true) return "да";
  if (v === false) return "нет";
  if (Array.isArray(v)) return v.length ? v.map((r) => `${r.invoice_id}: ${r.applied_minor}`).join(", ") : "ни к одному счёту";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)) return isoDateRu(v);
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return ruDateTime(v);
  return String(v).replace("added (copy of", "добавлен (копия").replace("added (customer paid duplicate", "добавлен (покупатель оплатил дубль");
}
function changeLine(c) {
  return `${refHuman(c.target)}: ${esc(CHANGE_FIELD_RU[c.field] || c.field)} <span class="faint">${esc(changeValue(c.before))}</span> → <b>${esc(changeValue(c.after))}</b>${c.note ? ` <span class="chip">${esc(NOTE_RU[c.note] || c.note)}</span>` : ""}`;
}
function diffBlock(d) {
  const base = state.ix.m.base_currency;
  const amt = (v) => (v ? moneyText(v, base) : "—").padStart(20);
  const fmt = (rows) => (rows ? rows.map((r) => `${accName(r.account).padEnd(30)} Дт ${amt(r.debit_minor)}   Кт ${amt(r.credit_minor)}`).join("\n") : "(проводки не было — документ в учёт не попадал)");
  return `<div class="diff"><div><h4>Проводка до ошибки</h4><pre class="before">${esc(fmt(d.before))}</pre></div><div><h4>Проводка после ошибки</h4><pre class="after">${esc(fmt(d.after))}</pre></div></div>`;
}
function viewProvenance() {
  const pv = state.data.provenance;
  if (!pv) return '<div class="card"><div class="empty">Нет данных</div></div>';
  const dis = pv.distractors.map((d) => `<tr><td>${esc(DISTRACTOR_RU[d.kind] || d.kind)}</td><td>${d.ids.map(refHuman).join(", ")}</td></tr>`).join("");
  return `<div class="grid-2">
    <div class="card"><div class="card-head"><div class="card-title">Ловушки — это не ошибки</div><span class="chip good">всё верно</span></div>
      <div class="card-body" style="padding-bottom:0"><p class="muted" style="margin:0 0 10px">Эти записи выглядят подозрительно, но учтены правильно. Хороший аудитор не должен их отмечать.</p></div>
      <div class="table-wrap" style="max-height:480px"><table><thead><tr><th>Что это</th><th>Записи</th></tr></thead><tbody>${dis || '<tr><td colspan="2"><div class="empty">—</div></td></tr>'}</tbody></table></div></div>
    <div class="card"><div class="card-head"><div class="card-title">Что генератор изменил в данных</div></div>
      <div class="card-body">${pv.changes.length ? pv.changes.map((c) => `<div style="margin-bottom:8px">${changeLine(c)}</div>`).join("") : '<span class="muted">Ничего — компания без ошибок.</span>'}</div></div>
    <div class="card"><div class="card-head"><div class="card-title">Технические параметры</div><span class="muted">для разработчиков</span></div>
      <div class="card-body"><div class="kv" style="margin-bottom:10px"><div>ID эпизода</div><div class="mono">${esc(state.ix.m.episode_id)}</div><div>Версия генератора</div><div class="mono">${esc(pv.generator_version)} · конфиг ${esc(pv.config_version)}</div></div>
      <pre class="mono" style="margin:0;white-space:pre-wrap;max-height:360px;overflow:auto">${esc(JSON.stringify({ seed: pv.seed, config: pv.config, company: pv.company }, null, 2))}</pre></div></div>
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
  else html = `<div class="empty">Запись не найдена</div>`;
  const title = table === "fx" ? `${id.split("/").slice(1).join(" → ")} · ${isoDateRu(id.slice(0, 10))}` : id;
  $("#drawer-title").innerHTML = `<div class="kind">${esc(TABLE_RU[table] || table)}</div><div class="rid">${esc(title)}</div>`;
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
  const line = (i, role) => `<div style="margin-bottom:6px">${typeChip(i.type)} <b>${role}</b><br><span class="muted">${esc(issueText(i))}</span></div>`;
  return `<div class="callout">${aff.map((i) => line(i, "Здесь ошибка")).join("")}${ev.map((i) => line(i, "Эта запись — доказательство")).join("")}</div>`;
}
function kv(pairs) { return `<div class="kv">${pairs.map(([k, v]) => `<div>${esc(k)}</div><div>${v}</div>`).join("")}</div>`; }
function ledgerTable(rows) {
  if (!rows || !rows.length) return '<p class="muted">В журнале этого месяца проводок нет — документ относится к другому месяцу.</p>';
  const base = state.ix.m.base_currency;
  return `<table><thead><tr><th>Счёт учёта</th><th class="num">Дебет</th><th class="num">Кредит</th></tr></thead><tbody>${rows
    .map((r) => `<tr class="${hlClass(`ledger:${r.row_id}`)}" data-ref="ledger:${esc(r.row_id)}"><td>${accCell(r.account)}</td><td class="num">${r.debit_minor ? money(r.debit_minor, base) : ""}</td><td class="num">${r.credit_minor ? money(r.credit_minor, base) : ""}</td></tr>`)
    .join("")}</tbody></table>`;
}
function periodNote(ts) { return inPeriod(ts) ? "" : ' <span class="chip warn">другой месяц</span>'; }
function drawerInvoice(i) {
  const ix = state.ix;
  const pays = ix.paysByInv.get(i.invoice_id) || [];
  const open = i.total_minor - (ix.applied.get(i.invoice_id) || 0);
  const rows = ix.rowsByInv.get(i.invoice_id);
  return `<section>${kv([
    ["Покупатель", `<span class="mono">${esc(i.entity_id)}</span>`],
    ["Дата счёта", tsCell(i.issued_at) + periodNote(i.issued_at)],
    ["Оплатить до", tsCell(i.due_at)],
    ["Сумма", money(i.total_minor, i.currency)],
    ["Осталось оплатить", open ? money(open, i.currency) : '<span class="chip good">оплачен полностью</span>'],
    ["Документ", `<span class="mono faint">${esc(i.doc_id)}</span>`],
  ])}</section>
  <section><h3>Что продано</h3><table><thead><tr><th>Позиция</th><th class="num">Кол-во</th><th class="num">Цена</th><th class="num">Сумма</th></tr></thead><tbody>${i.line_items
    .map((li) => `<tr><td>${esc(li.description)}</td><td class="num">${li.quantity}</td><td class="num">${money(li.unit_price_minor, i.currency)}</td><td class="num">${money(li.amount_minor, i.currency)}</td></tr>`)
    .join("")}</tbody></table></section>
  <section><h3>Кто и сколько заплатил</h3>${pays.length ? `<table><tbody>${pays.map(({ pay, applied }) => `<tr data-ref="payments:${esc(pay.payment_id)}"><td>${refLink(`payments:${pay.payment_id}`)}</td><td>${tsCell(pay.timestamp)}</td><td class="num">${money(applied, i.currency)}</td></tr>`).join("")}</tbody></table>` : '<p class="muted">Ни один платёж не зачтён в оплату этого счёта.</p>'}</section>
  <section><h3>Как счёт отражён в журнале</h3>${ledgerTable(rows)}</section>`;
}
function drawerPayment(x) {
  const ix = state.ix;
  const ua = x.kind === "receipt" ? unapplied(x) : 0;
  return `<section>${kv([
    ["Тип", x.kind === "refund" ? "возврат денег покупателю" : "оплата от покупателя"],
    ["Покупатель", `<span class="mono">${esc(x.entity_id)}</span>`],
    ["Дата платежа", tsCell(x.timestamp) + periodNote(x.timestamp)],
    ["Сумма", money(x.amount_minor, x.currency)],
    ["Не зачтено в счета", ua ? `<span class="chip warn">${money(ua, x.currency)}</span>` : "—"],
    ["Возврат по платежу", x.refund_of ? refLink(`payments:${x.refund_of}`) : "—"],
    ["Документ", `<span class="mono faint">${esc(x.doc_id)}</span>`],
  ])}</section>
  <section><h3>В оплату каких счетов</h3>${x.invoice_refs.length ? `<table><tbody>${x.invoice_refs.map((r) => {
    const inv = ix.inv.get(r.invoice_id);
    return `<tr data-ref="invoices:${esc(r.invoice_id)}"><td>${refLink(`invoices:${r.invoice_id}`)}</td><td class="num">${money(r.applied_minor, x.currency)}</td><td class="num faint">из ${inv ? money(inv.total_minor, inv.currency) : "?"}</td></tr>`;
  }).join("")}</tbody></table>` : '<p class="muted">Платёж не зачтён ни в один счёт.</p>'}</section>
  <section><h3>Как платёж отражён в журнале</h3>${ledgerTable(ix.rowsByPay.get(x.payment_id))}</section>`;
}
function drawerRow(r) {
  const ix = state.ix;
  const base = ix.m.base_currency;
  let siblings = [];
  if (r.payment_id) siblings = ix.rowsByPay.get(r.payment_id);
  else if (r.invoice_id) siblings = ix.rowsByInv.get(r.invoice_id);
  else siblings = state.data.public.ledger.filter((x) => x.timestamp === r.timestamp && !x.invoice_id && !x.payment_id);
  return `<section>${kv([
    ["Дата и время", tsCell(r.timestamp)],
    ["Счёт учёта", accCell(r.account)],
    ["Дебет", r.debit_minor ? money(r.debit_minor, base) : "—"],
    ["Кредит", r.credit_minor ? money(r.credit_minor, base) : "—"],
    ["Покупатель", dash(r.entity_id)],
    ["Счёт покупателю", dash(r.invoice_id, r.invoice_id && `invoices:${r.invoice_id}`)],
    ["Платёж", dash(r.payment_id, r.payment_id && `payments:${r.payment_id}`)],
  ])}</section>
  <section><h3>Вся проводка целиком</h3>${ledgerTable(siblings)}<p class="faint" style="margin:8px 0 0">В каждой проводке сумма дебета равна сумме кредита.</p></section>`;
}
function drawerFx(r) {
  const same = state.data.public.fx.filter((x) => x.source_currency === r.source_currency);
  const i = same.indexOf(r);
  const near = same.slice(Math.max(0, i - 3), i + 4);
  return `<section>${kv([["Дата", esc(isoDateRu(r.date))], ["Курс", `1 ${esc(r.source_currency)} = <span class="mono">${esc(r.rate)}</span> ${esc(r.target_currency)}`]])}</section>
  <section><h3>Курсы в соседние дни</h3><table><tbody>${near.map((x) => {
    const ref = `fx:${x.date}/${x.source_currency}/${x.target_currency}`;
    return `<tr class="${x === r ? "hl-evidence" : hlClass(ref)}" data-ref="${esc(ref)}"><td class="mono">${esc(isoDateRu(x.date))}</td><td class="num">${esc(x.rate)}</td></tr>`;
  }).join("")}</tbody></table><p class="faint">По выходным курс не публикуется — берётся последний опубликованный.</p></section>`;
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
  const action = t.closest("[data-action]");
  if (action) {
    state.introHidden = action.dataset.action === "intro-hide";
    store.set("auditgym.introHidden", state.introHidden);
    renderView();
    return;
  }
  const tab = t.closest("[data-tab]");
  if (tab) { setTab(tab.dataset.tab); return; }
  const pageBtn = t.closest("[data-page]");
  if (pageBtn) { state.page += Number(pageBtn.dataset.page); renderView(); return; }
  const acc = t.closest("[data-filter-account]");
  if (acc) { setTab("ledger"); state.f.account = acc.dataset.filterAccount; renderView(); return; }
  const ccy = t.closest("[data-filter-ccy]");
  if (ccy) { setTab("invoices"); state.f.ccy = ccy.dataset.filterCcy; renderView(); return; }
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
  if (window.innerWidth <= 900) $("#sidebar").classList.remove("open");
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
    $("#gen-preset").innerHTML = pr.presets.map((p) => `<option value="${esc(p)}"${p === "interactions" ? " selected" : ""}>${esc(PRESET_RU[p] || p)}</option>`).join("");
    $("#side-foot").innerHTML = `Все компании, люди и деньги вымышлены.<br>Генератор v${esc(pr.generator_version)}`;
  } catch (e) {
    $("#company").textContent = "Сервер недоступен";
    $("#meta").textContent = e.message;
    return;
  }
  await route();
})();
