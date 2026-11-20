/* Live cyberpunk workspace. Financial data and policy results come only from the team API. */
"use strict";
(() => {
  const root = document.getElementById("audit-prototype"),
    el = (id) => root.querySelector("#ag-" + id);
  const esc = (v) =>
    String(v ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const names = {
    duplicate_invoice: "Дубли счетов",
    payment_allocation: "Распределение платежей",
    fx_conversion: "Конверсия валют",
    period_cutoff: "Граница периода",
  };
  const policyNames = ["Reconciler", "Oracle", "FlagAll", "RandomExplorer"];
  const titles = {
    overview: ["Обзор компании", "Документы и результаты проверки"],
    companies: ["Компании", "Рабочий каталог этого браузера"],
    episodes: ["Эпизоды", "Реальные документы генератора команды"],
    investigation: [
      "Расследование эпизода",
      "Документы, доказательства и траектория агента",
    ],
    comparison: ["Сравнение агентов", "Результаты AuditEnv и grader команды"],
    reports: ["Отчёты", "Выводы агента и ручные подтверждения"],
  };
  const storageKey = "auditgym.live.workspace.v1";
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
  } catch {}
  let companies = Array.isArray(saved.companies) ? saved.companies : [],
    hidden = Array.isArray(saved.hidden) ? saved.hidden : [],
    generated = Array.isArray(saved.generated) ? saved.generated : [],
    aliases = saved.aliases || {},
    confirmations = saved.confirmations || {};
  let episodes = [],
    presets = [],
    selected = null,
    publicData = null,
    page = "overview",
    agent = "Reconciler",
    findingIndex = 0,
    docId = "",
    evidenceId = "",
    cursor = 0,
    table = "all",
    busy = false,
    editCompany = null,
    editEpisode = null,
    deletion = null,
    viewToken = 0;
  const cache = new Map(),
    runs = new Map();
  const number = (n) =>
    new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(n);
  function money(n, ccy) {
    const exp = publicData?.manifest.currencies[ccy]?.exponent ?? 2;
    return number(n / 10 ** exp) + " " + ccy;
  }
  const recordId = (r) => r.invoice_id || r.payment_id || r.row_id || r.doc_id;
  const company = () => companies.find((c) => c.id === selected?.companyId);
  const companyName = (id) =>
    aliases[id] || companies.find((c) => c.id === id)?.name || "Компания";
  const runKey = (id = selected?.id, p = agent) => id + ":" + p;
  const run = () => runs.get(runKey());
  const findings = () => run()?.findings || [];
  const selectedFinding = () => findings()[findingIndex];
  const confirmationKey = (i) => runKey() + ":" + i;
  function save() {
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify({
          companies,
          hidden,
          generated,
          aliases,
          confirmations,
        }),
      );
    } catch {
      status("Браузер не разрешает сохранить рабочий каталог");
    }
  }
  function status(message, error = false) {
    el("status").textContent = message;
    el("status").style.color = error ? "#ffa5ad" : "";
  }
  async function api(path, body) {
    const response = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response
      .json()
      .catch(() => ({ error: "Некорректный ответ сервера" }));
    if (!response.ok)
      throw Error(data.error || "Ошибка API " + response.status);
    return data;
  }
  function options(items, value) {
    return items
      .map(
        ([id, label]) =>
          '<option value="' +
          esc(id) +
          '" ' +
          (id === value ? "selected" : "") +
          ">" +
          esc(label) +
          "</option>",
      )
      .join("");
  }
  function button(label, attr, primary = false) {
    return (
      '<button class="ag-button ' +
      (primary ? "ag-primary" : "") +
      '" ' +
      attr +
      ">" +
      esc(label) +
      "</button>"
    );
  }
  function empty(cols, text) {
    return (
      '<tr><td class="ag-empty" colspan="' +
      cols +
      '">' +
      esc(text) +
      "</td></tr>"
    );
  }
  function totals(list) {
    const sums = {};
    for (const f of list)
      sums[f.currency] =
        (sums[f.currency] || 0) + Math.abs(f.claimed_amount_minor);
    return (
      Object.entries(sums)
        .map(([c, n]) => money(n, c))
        .join(" · ") || "—"
    );
  }
  function summary(ep, pub) {
    return {
      id: ep.id,
      companyId: ep.companyId,
      source: ep.source,
      name: pub.manifest.company_name,
      counts: pub.manifest.counts,
      period: pub.manifest.period_start,
      base: pub.manifest.base_currency,
    };
  }
  async function load(ep) {
    if (cache.has(ep.id)) return cache.get(ep.id);
    const s = ep.source;
    const path = s.preset
      ? "/api/generate?" + new URLSearchParams(s)
      : "/api/episodes/" +
        encodeURIComponent(s.split) +
        "/" +
        encodeURIComponent(s.name);
    const data = await api(path);
    cache.set(ep.id, data.public);
    Object.assign(ep, summary(ep, data.public));
    return data.public;
  }
  async function choose(id, destination = page) {
    const token = ++viewToken;
    selected = episodes.find((e) => e.id === id) || null;
    publicData = null;
    findingIndex = 0;
    docId = "";
    evidenceId = "";
    cursor = 0;
    page = destination;
    render();
    if (!selected) return;
    status("Загружаем документы…");
    try {
      const ep = selected,
        pub = await load(ep);
      if (token !== viewToken) return;
      publicData = pub;
      docId = pub.invoices[0]?.invoice_id || pub.payments[0]?.payment_id || "";
      status("");
      render();
    } catch (e) {
      if (token === viewToken) {
        status("Не удалось загрузить эпизод: " + e.message, true);
        render();
      }
    }
  }
  function go(next) {
    if (!titles[next]) return;
    page = next;
    render();
  }
  function render() {
    root.querySelectorAll(".ag-navigation [data-page]").forEach((b) => {
      if (b.dataset.page === page) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
    for (const p of Object.keys(titles)) el(p).hidden = p !== page;
    root
      .querySelectorAll("form input,form select,form button")
      .forEach((control) => (control.disabled = busy));
    el("active-policy").textContent = agent;
    el("timeline").closest("section").querySelector(".ag-badge").textContent =
      agent;
    el("company-form").querySelector("h2").textContent = editCompany
      ? "Редактирование компании"
      : "Новая компания";
    el("company-form").querySelector("[type=submit]").textContent = editCompany
      ? "Сохранить изменения"
      : "Создать компанию";
    el("generator-form").querySelector("h2").textContent = editEpisode
      ? "Редактирование эпизода"
      : "Генерация эпизода";
    el("title").textContent = titles[page][0];
    el("subtitle").textContent = titles[page][1];
    el("company").textContent = selected
      ? companyName(selected.companyId)
      : "Нет выбранного эпизода";
    el("episode").innerHTML = options(
      episodes.map((e) => [
        e.id,
        companyName(e.companyId) +
          " · " +
          (e.source.name || e.source.preset + " / " + e.source.seed),
      ]),
      selected?.id,
    );
    el("episode").disabled = busy || !episodes.length;
    el("run").disabled = busy || !selected || !publicData;
    el("run").hidden = ["companies", "episodes", "reports"].includes(page);
    el("run").textContent = busy
      ? "Выполняется…"
      : page === "comparison"
        ? "Запустить сравнение"
        : "Запустить " + agent;
    el("empty-state").hidden =
      !!selected || ["companies", "episodes"].includes(page);
    for (const p of ["overview", "investigation", "comparison", "reports"])
      if (!selected && p === page) el(p).hidden = true;
    renderCompanies();
    renderEpisodes();
    if (!publicData) return;
    renderOverview();
    renderInvestigation();
    renderComparison();
    renderReports();
  }
  function renderOverview() {
    const p = publicData,
      m = p.manifest,
      fs = findings();
    el("metrics").innerHTML = [
      ["Документы", m.counts.documents, "Счета и платежи"],
      ["Проводки", m.counts.ledger_rows, "Базовая валюта — " + m.base_currency],
      [
        "Выводы агента",
        run() ? fs.length : "—",
        run()
          ? "Подтверждено: " +
            fs.filter((_, i) => confirmations[confirmationKey(i)]).length
          : "Запустите проверку",
      ],
      ["Заявленные суммы", totals(fs), "По валютам, без смешения единиц"],
    ]
      .map(
        ([l, v, n]) =>
          '<div class="ag-card"><div class="ag-stat-label">' +
          esc(l) +
          '</div><div class="ag-value">' +
          esc(v) +
          '</div><div class="ag-stat-note">' +
          esc(n) +
          "</div></div>",
      )
      .join("");
    const amounts = [0, 0, 0, 0],
      start = Date.parse(m.period_start),
      end = Date.parse(m.period_end);
    for (const r of p.ledger) {
      const time = Date.parse(r.timestamp),
        i = Math.floor(((time - start) / (end - start)) * 4);
      if (i >= 0 && i < 4) amounts[i] += r.debit_minor;
    }
    el("period").innerHTML = options(
      [
        [
          m.period_start,
          new Date(m.period_start).toLocaleDateString("ru-RU", {
            month: "long",
            year: "numeric",
            timeZone: "UTC",
          }),
        ],
      ],
      m.period_start,
    );
    el("chart").innerHTML = amounts
      .map(
        (n, i) =>
          '<div class="ag-column"><div class="ag-bar" style="height:' +
          (n / Math.max(...amounts, 1)) * 90 +
          '%"><span class="ag-chart-value">' +
          esc(number(n / 10 ** m.currencies[m.base_currency].exponent / 1000)) +
          "</span></div><small>Часть " +
          (i + 1) +
          "</small></div>",
      )
      .join("");
    el("chart").setAttribute(
      "aria-label",
      "Дебетовый оборот за четыре равные части периода: " +
        amounts.map((n) => money(n, m.base_currency)).join(", "),
    );
    el("chart-total").textContent =
      "Всего " +
      money(
        amounts.reduce((a, b) => a + b, 0),
        m.base_currency,
      );
    const max = Math.max(
      1,
      ...Object.keys(names).map((k) => fs.filter((f) => f.type === k).length),
    );
    el("risks").innerHTML = Object.entries(names)
      .map(([k, n]) => {
        const count = fs.filter((f) => f.type === k).length;
        return (
          '<div class="ag-risk-line"><span>' +
          n +
          '</span><div class="ag-track"><div class="ag-risk-fill" style="width:' +
          (count / max) * 100 +
          '%"></div></div><span>' +
          count +
          "</span></div>"
        );
      })
      .join("");
    el("risk-total").textContent = run()
      ? fs.length + " выводов"
      : "Нет запуска";
    const query = el("search").value.trim().toLowerCase(),
      filter = el("filter").value;
    const visible = fs
      .map((f, i) => ({ f, i }))
      .filter(
        ({ f }) =>
          (filter === "all" || f.type === filter) &&
          JSON.stringify(f.affected_ids).toLowerCase().includes(query),
      );
    el("table-count").textContent = visible.length + " / " + fs.length;
    el("findings").innerHTML =
      visible
        .map(
          ({ f, i }) =>
            "<tr><td>" +
            button(f.affected_ids[0], 'data-finding="' + i + '"') +
            "</td><td>" +
            esc(names[f.type]) +
            '</td><td class="ag-number">' +
            esc(money(f.claimed_amount_minor, f.currency)) +
            '</td><td><span class="ag-badge ' +
            (confirmations[confirmationKey(i)] ? "done" : "") +
            '">' +
            (confirmations[confirmationKey(i)] ? "Подтверждён" : "К проверке") +
            "</span></td></tr>",
        )
        .join("") ||
      empty(
        4,
        run()
          ? "Нет выводов по выбранному фильтру"
          : "Запустите агента для поиска расхождений",
      );
    el("timeline").innerHTML =
      '<div class="ag-event"><span class="ag-event-num">1</span><div><strong>Документы загружены из API</strong><p class="ag-sub">' +
      esc(m.episode_id) +
      '</p></div></div><div class="ag-event"><span class="ag-event-num">2</span><div><strong>' +
      esc(run() ? "Проверка завершена" : "Ожидает запуска") +
      '</strong><p class="ag-sub">' +
      esc(agent) +
      (run() ? " · " + run().metrics.steps + " шагов" : "") +
      "</p></div></div>";
  }
  function documents() {
    const p = publicData;
    return [
      ...p.invoices.map((r) => ({
        id: r.invoice_id,
        date: r.issued_at,
        amount: r.total_minor,
        currency: r.currency,
        table: "invoices",
        record: r,
      })),
      ...p.payments.map((r) => ({
        id: r.payment_id,
        date: r.timestamp,
        amount: r.amount_minor,
        currency: r.currency,
        table: "payments",
        record: r,
      })),
    ];
  }
  function lookup(id) {
    const [kind, key] = id.includes(":") ? id.split(":") : [null, id];
    const p = publicData;
    if (!p) return null;
    if (kind === "policy") return p.policy;
    if (kind === "manifest") return p.manifest;
    if (kind === "fx") {
      return p.fx.find(
        (r) => `${r.date}/${r.source_currency}/${r.target_currency}` === key,
      );
    }
    for (const t of kind ? [kind] : ["invoices", "payments", "ledger", "fx"]) {
      const record = p[t]?.find((r) => Object.values(r).some((v) => v === key));
      if (record) return record;
    }
    return null;
  }
  function renderInvestigation() {
    const fs = findings(),
      f = selectedFinding(),
      rows = documents().filter((d) => table === "all" || d.table === table),
      logs = run()?.trajectory || [];
    cursor = Math.max(0, Math.min(cursor, logs.length - 1));
    el("records").innerHTML = rows
      .map(
        (d) =>
          '<tr class="' +
          (docId === d.id ? "ag-selected" : "") +
          '"><td>' +
          button(d.id, 'data-document="' + esc(d.id) + '"') +
          "</td><td>" +
          esc(new Date(d.date).toLocaleDateString("ru-RU")) +
          '</td><td class="ag-number">' +
          esc(money(d.amount, d.currency)) +
          "</td></tr>",
      )
      .join("");
    el("record-count").textContent = rows.length + " документов";
    root
      .querySelectorAll("[data-table]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.table === table)),
      );
    el("issue-type").textContent = f ? names[f.type] : "Документ";
    el("amount").textContent = f
      ? money(f.claimed_amount_minor, f.currency)
      : "—";
    el("booked").textContent = f ? f.affected_ids.join(", ") : docId;
    el("expected").textContent = f ? f.currency : "—";
    el("explanation").textContent = f
      ? f.explanation || "Вывод агента требует проверки по документам"
      : "Выберите документ или запустите агента";
    const evidence = f?.evidence_ids || [];
    if (!evidence.includes(evidenceId)) evidenceId = evidence[0] || docId;
    el("evidence").innerHTML = evidence
      .map(
        (id) =>
          '<button data-evidence="' +
          esc(id) +
          '" aria-pressed="' +
          (id === evidenceId) +
          '">' +
          esc(id) +
          "</button>",
      )
      .join("");
    el("proof-detail").textContent = JSON.stringify(
      lookup(evidenceId) || {
        id: evidenceId,
        message: "Запись с этим ID не найдена в публичных документах",
      },
      null,
      2,
    );
    el("proof-count").textContent = evidence.length + " ID";
    el("step-count").textContent = logs.length
      ? cursor + 1 + " / " + logs.length
      : "Нет запуска";
    const first = Math.max(0, Math.min(cursor - 1, logs.length - 4));
    el("steps").innerHTML = logs
      .slice(first, first + 4)
      .map(
        (r, i) =>
          '<button class="ag-step" data-step="' +
          (first + i) +
          '" aria-pressed="' +
          (first + i === cursor) +
          '"><span class="ag-step-no">Шаг ' +
          r.step +
          "</span>" +
          esc(r.action.name) +
          "</button>",
      )
      .join("");
    el("step-detail").textContent = logs.length
      ? JSON.stringify(logs[cursor], null, 2)
      : "После запуска здесь появится реальная траектория AuditEnv";
    el("prev").disabled = busy || cursor <= 0;
    el("next").disabled = busy || cursor >= logs.length - 1;
    el("confirm").disabled = busy || !f;
    el("confirm").textContent =
      f && confirmations[confirmationKey(findingIndex)]
        ? "Вывод подтверждён"
        : "Подтвердить вывод";
  }
  function renderCompanies() {
    el("company-total").textContent = companies.length;
    el("episode-total").textContent = episodes.length;
    el("company-cards").innerHTML =
      companies
        .map((c) => {
          const eps = episodes.filter((e) => e.companyId === c.id);
          return (
            '<section class="ag-card"><div class="ag-company-title"><span class="ag-company-avatar">' +
            esc(companyName(c.id)[0]) +
            "</span><div><h2>" +
            esc(companyName(c.id)) +
            '</h2><p class="ag-sub">' +
            esc(c.sector || "Синтетическая компания") +
            '</p></div></div><div class="ag-company-stats"><div><span>Эпизоды</span><b>' +
            eps.length +
            '</b></div><div><span>Каталог</span><b>Локальный</b></div></div><div class="ag-controls">' +
            (eps[0]
              ? button(
                  "Открыть компанию",
                  'data-open="' + esc(eps[0].id) + '"',
                  true,
                )
              : "") +
            button("Добавить эпизод", 'data-generate="' + esc(c.id) + '"') +
            '</div><div class="ag-controls ag-management-actions">' +
            button("Редактировать", 'data-edit-company="' + esc(c.id) + '"') +
            button("Удалить", 'data-delete-company="' + esc(c.id) + '"') +
            "</div></section>"
          );
        })
        .join("") ||
      '<p class="ag-sub">Создайте компанию, чтобы добавить эпизод</p>';
    el("generator-company").innerHTML = options(
      companies.map((c) => [c.id, companyName(c.id)]),
      el("generator-company").value,
    );
    el("new-episode").disabled = !companies.length;
  }
  function renderEpisodes() {
    const previous = el("company-filter").value;
    el("company-filter").innerHTML = options(
      [
        ["all", "Все компании"],
        ...companies.map((c) => [c.id, companyName(c.id)]),
      ],
      previous || "all",
    );
    const eps = episodes.filter(
      (e) =>
        el("company-filter").value === "all" ||
        e.companyId === el("company-filter").value,
    );
    el("episode-list").innerHTML =
      eps
        .map(
          (e) =>
            '<tr class="' +
            (e.id === selected?.id ? "ag-selected" : "") +
            '"><td>' +
            button(
              e.source.name || e.source.preset,
              'data-select-episode="' + esc(e.id) + '"',
            ) +
            '<p class="ag-sub">' +
            esc(companyName(e.companyId)) +
            '</p><div class="ag-row-actions">' +
            button("Изменить", 'data-edit-episode="' + esc(e.id) + '"') +
            button("Удалить", 'data-delete-episode="' + esc(e.id) + '"') +
            "</div></td><td>" +
            esc(e.counts?.documents ?? "—") +
            "</td><td>" +
            esc(e.source.seed ?? e.source.split) +
            "</td><td>" +
            esc(e.base || "—") +
            "</td><td>" +
            esc(runs.has(e.id + ":Reconciler") ? "Выполнена" : "Нет запуска") +
            "</td></tr>",
        )
        .join("") || empty(5, "Эпизодов нет");
    el("selected-episode").textContent =
      selected?.source.name || selected?.source.preset || "—";
    el("episode-detail").textContent = selected
      ? JSON.stringify(selected.source)
      : "Выберите эпизод";
    el("episode-open").disabled = !selected;
  }
  function renderComparison() {
    const currentOnly = el("compare-scope").value === "current";
    const sort = el("compare-sort").value || "f1";
    const results = policyNames
      .map((p) => {
        const rs = [...runs.entries()]
          .filter(
            ([k]) =>
              k.endsWith(":" + p) &&
              (!currentOnly || k === runKey(selected.id, p)),
          )
          .map(([, r]) => r.metrics);
        const avg = (k) =>
          rs.length
            ? rs.reduce((n, r) => n + (r[k] ?? 0), 0) / rs.length
            : null;
        return {
          policy: p,
          count: rs.length,
          precision: avg("precision"),
          recall: avg("recall"),
          f1: avg("f1"),
          reward: avg("reward"),
          steps: avg("steps"),
        };
      })
      .sort((a, b) =>
        sort === "steps"
          ? (a.steps ?? Infinity) - (b.steps ?? Infinity)
          : (b[sort] ?? -Infinity) - (a[sort] ?? -Infinity),
      );
    el("agent-list").innerHTML = results
      .map(
        (r) =>
          '<tr class="' +
          (r.policy === agent ? "ag-selected" : "") +
          '"><td>' +
          button(r.policy, 'data-agent="' + r.policy + '"') +
          "</td>" +
          ["precision", "recall", "f1", "reward", "steps"]
            .map(
              (k) =>
                '<td class="ag-number">' +
                (r[k] === null ? "—" : number(r[k])) +
                "</td>",
            )
            .join("") +
          "</tr>",
      )
      .join("");
    el("agent-name").textContent = agent;
    el("compare-label").textContent = currentOnly
      ? "Выбранный эпизод"
      : "Выполненные прогоны";
    el("agent-description").textContent =
      agent === "Oracle"
        ? "Привилегированный эталон: получает скрытый ответ. Это верхняя граница качества."
        : "Политика работает с публичными наблюдениями AuditEnv";
    el("agent-summary").textContent =
      "Сначала запустите сравнение для выбранного эпизода. Средние учитывают только выполненные прогоны.";
    el("agent-limits").textContent = "Лимит — 100 шагов · seed политики — 42";
  }
  function report() {
    const fs = findings()
      .map((f, i) => ({
        ...f,
        manually_confirmed: !!confirmations[confirmationKey(i)],
      }))
      .filter(
        (f) => el("report-scope").value !== "confirmed" || f.manually_confirmed,
      );
    return {
      company: companyName(selected.companyId),
      source: selected.source,
      episode_id: publicData.manifest.episode_id,
      policy: agent,
      metrics: run()?.metrics || null,
      privileged: agent === "Oracle",
      findings: fs,
      manual_confirmation_is_not_grader_result: true,
    };
  }
  function renderReports() {
    const r = report();
    el("report-company").textContent =
      r.company + " · " + r.episode_id + " · " + agent;
    el("report-status").textContent = run()
      ? "Проверка выполнена"
      : "Агент не запущен";
    el("report-summary").innerHTML =
      '<div><span class="ag-stat-label">Выводы в отчёте</span><b>' +
      r.findings.length +
      '</b></div><div><span class="ag-stat-label">F1 grader</span><b>' +
      (r.metrics ? number(r.metrics.f1) : "—") +
      '</b></div><div><span class="ag-stat-label">Награда</span><b>' +
      (r.metrics ? number(r.metrics.reward) : "—") +
      "</b></div>";
    el("report-progress").textContent =
      "Ручные подтверждения сохраняются в браузере и не меняют метрики grader";
    el("report-findings").innerHTML =
      r.findings
        .map(
          (f) =>
            "<tr><td>" +
            esc(f.affected_ids.join(", ")) +
            '<p class="ag-sub">' +
            esc(names[f.type]) +
            '</p></td><td class="ag-number">' +
            esc(money(f.claimed_amount_minor, f.currency)) +
            '</td><td class="ag-report-proof">' +
            esc(f.evidence_ids.join(", ")) +
            "</td><td>" +
            esc(f.manually_confirmed ? "Подтверждён" : "К проверке") +
            "</td></tr>",
        )
        .join("") || empty(4, "Нет выводов в выбранном отчёте");
    el("report-preview").textContent = reportText(r);
    el("report-filename").textContent = filename();
    el("report-download").disabled = !run();
  }
  function reportText(r) {
    return [
      r.company,
      r.episode_id,
      "Политика: " + r.policy,
      "Метрики grader: " + JSON.stringify(r.metrics),
      "Ручное подтверждение не является оценкой grader",
      ...r.findings.map(
        (f) =>
          names[f.type] +
          " | " +
          f.affected_ids.join(", ") +
          " | " +
          money(f.claimed_amount_minor, f.currency) +
          " | " +
          (f.manually_confirmed ? "подтверждён" : "к проверке") +
          " | " +
          f.evidence_ids.join(", "),
      ),
    ].join("\n");
  }
  function filename() {
    return (
      "auditgym-" +
      (publicData?.manifest.episode_id || "report") +
      "-" +
      agent +
      "." +
      el("report-format").value
    );
  }
  async function execute(compare = false) {
    if (busy || !selected) return;
    busy = true;
    const ep = selected;
    render();
    status("Выполняется реальный прогон AuditEnv…");
    try {
      for (const p of compare ? policyNames : [agent]) {
        const result = await api("/api/run", {
          source: ep.source,
          policy: p,
          seed: 42,
        });
        runs.set(runKey(ep.id, p), result);
      }
      if (selected?.id === ep.id) {
        cursor = (run()?.trajectory.length || 1) - 1;
        findingIndex = 0;
        if (!compare) page = "investigation";
      }
      status("Проверка завершена. Метрики рассчитаны grader команды");
    } catch (e) {
      status("Ошибка запуска: " + e.message, true);
    } finally {
      busy = false;
      render();
    }
  }
  function requestDelete(kind, id) {
    deletion = { kind, id };
    el("delete-title").textContent =
      "Удалить " +
      (kind === "company" ? "компанию" : "эпизод") +
      " из каталога?";
    el("delete-description").textContent =
      "Удаление относится к рабочему каталогу этого браузера";
    el("delete-impact").textContent =
      kind === "company"
        ? "Её эпизоды и локальные подтверждения будут удалены из каталога. Опубликованные данные команды сохранятся."
        : "Опубликованный исходник команды не изменится";
    el("delete-dialog").showModal();
  }
  function openGenerator(owner, episode = null) {
    editEpisode = episode;
    go("episodes");
    el("generator-form").hidden = false;
    el("generator-company").value = owner || companies[0]?.id;
    el("generator-preset").value = episode?.source.preset || presets[0];
    el("generator-seed").value = episode?.source.seed ?? 42;
    el("generator-error").textContent = "";
    el("preset-description").textContent =
      "Пресет командного генератора: " + el("generator-preset").value;
  }
  root.addEventListener("click", (event) => {
    const b = event.target.closest("button");
    if (!b || busy) return;
    const d = b.dataset;
    if (d.page) go(d.page);
    if (b.hasAttribute("data-open-investigation")) go("investigation");
    if (d.open) choose(d.open, "overview");
    if (d.selectEpisode) choose(d.selectEpisode, "episodes");
    if (d.finding !== undefined) {
      findingIndex = Number(d.finding);
      docId = (selectedFinding()?.affected_ids[0] || "").split(":").at(-1);
      go("investigation");
    }
    if (d.document) {
      docId = d.document;
      const i = findings().findIndex((f) =>
        f.affected_ids.some((id) => id.endsWith(":" + docId)),
      );
      findingIndex = i;
      evidenceId = docId;
      renderInvestigation();
    }
    if (d.evidence) {
      evidenceId = d.evidence;
      renderInvestigation();
    }
    if (d.step !== undefined) {
      cursor = Number(d.step);
      renderInvestigation();
    }
    if (d.table) {
      table = d.table;
      renderInvestigation();
    }
    if (d.agent) {
      agent = d.agent;
      findingIndex = 0;
      render();
    }
    if (d.generate) openGenerator(d.generate);
    if (d.editCompany) {
      editCompany = d.editCompany;
      go("companies");
      el("company-name").value = companyName(editCompany);
      el("company-sector").value =
        companies.find((c) => c.id === editCompany)?.sector ||
        "Оптовая торговля";
      el("company-form").hidden = false;
    }
    if (d.deleteCompany) requestDelete("company", d.deleteCompany);
    if (d.deleteEpisode) requestDelete("episode", d.deleteEpisode);
    if (d.editEpisode) {
      const ep = episodes.find((e) => e.id === d.editEpisode);
      openGenerator(ep.companyId, ep);
    }
  });
  el("episode").onchange = (e) => choose(e.target.value);
  el("run").onclick = () => execute(page === "comparison");
  el("search").oninput = renderOverview;
  el("filter").onchange = renderOverview;
  el("company-filter").onchange = renderEpisodes;
  el("compare-scope").onchange = renderComparison;
  el("compare-sort").onchange = renderComparison;
  el("compare-open").onclick = () => go("investigation");
  el("episode-open").onclick = () => go("overview");
  el("back").onclick = () => go("overview");
  el("prev").onclick = () => {
    cursor--;
    renderInvestigation();
  };
  el("next").onclick = () => {
    cursor++;
    renderInvestigation();
  };
  el("confirm").onclick = () => {
    if (!selectedFinding()) return;
    confirmations[confirmationKey(findingIndex)] = true;
    save();
    render();
  };
  el("report-scope").onchange = renderReports;
  el("report-format").onchange = renderReports;
  el("report-download").onclick = () => {
    if (!run()) return;
    const r = report(),
      format = el("report-format").value;
    const cell = (v) => '"' + String(v ?? "").replace(/"/g, '""') + '"';
    const csv = [
      [
        "type",
        "affected_ids",
        "claimed_amount_minor",
        "currency",
        "evidence_ids",
        "manually_confirmed",
      ],
      ...r.findings.map((f) => [
        f.type,
        f.affected_ids.join(";"),
        f.claimed_amount_minor,
        f.currency,
        f.evidence_ids.join(";"),
        f.manually_confirmed,
      ]),
    ]
      .map((row) => row.map(cell).join(","))
      .join("\r\n");
    const text =
      format === "json"
        ? JSON.stringify(r, null, 2)
        : format === "csv"
          ? "\ufeff" + csv
          : reportText(r);
    const url = URL.createObjectURL(
      new Blob([text], {
        type:
          format === "json"
            ? "application/json;charset=utf-8"
            : format === "csv"
              ? "text/csv;charset=utf-8"
              : "text/plain;charset=utf-8",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = filename();
    root.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    el("report-download-status").textContent = "Отчёт подготовлен";
  };
  el("new-company").onclick = () => {
    editCompany = null;
    el("company-form").reset();
    el("company-error").textContent = "";
    el("company-form").hidden = false;
  };
  el("company-cancel").onclick = () => (el("company-form").hidden = true);
  el("company-form").onsubmit = (e) => {
    e.preventDefault();
    const name = el("company-name").value.trim();
    if (
      name.length < 2 ||
      name.length > 48 ||
      /[<>&\x00-\x1f]/.test(name) ||
      companies.some(
        (c) =>
          c.id !== editCompany &&
          companyName(c.id).toLowerCase() === name.toLowerCase(),
      )
    ) {
      el("company-error").textContent =
        "Введите уникальное название из 2–48 символов без <, > и &";
      return;
    }
    if (editCompany) {
      aliases[editCompany] = name;
      companies.find((c) => c.id === editCompany).sector =
        el("company-sector").value;
    } else
      companies.push({
        id: "local-" + crypto.randomUUID(),
        name,
        sector: el("company-sector").value,
      });
    el("company-form").hidden = true;
    save();
    render();
  };
  el("new-episode").onclick = () => openGenerator();
  el("generator-cancel").onclick = () => (el("generator-form").hidden = true);
  el("generator-preset").onchange = () =>
    (el("preset-description").textContent =
      "Пресет командного генератора: " + el("generator-preset").value);
  el("generator-form").onsubmit = async (e) => {
    e.preventDefault();
    const raw = el("generator-seed").value,
      seed = Number(raw),
      preset = el("generator-preset").value,
      owner = el("generator-company").value;
    if (
      !/^\d+$/.test(raw) ||
      !Number.isSafeInteger(seed) ||
      seed < 0 ||
      seed > 1e9 ||
      !companies.some((c) => c.id === owner) ||
      !presets.includes(preset)
    ) {
      el("generator-error").textContent =
        "Выберите компанию, пресет и целый seed от 0 до 1 000 000 000";
      return;
    }
    busy = true;
    render();
    try {
      const source = { preset, seed },
        data = await api("/api/generate?" + new URLSearchParams(source));
      const duplicate = episodes.find(
        (ep) =>
          ep.companyId === owner &&
          ep.source.preset === preset &&
          ep.source.seed === seed &&
          ep.id !== editEpisode?.id,
      );
      if (duplicate) throw Error("Эпизод с этими параметрами уже есть");
      const ep = {
        id: "generated-" + crypto.randomUUID(),
        companyId: owner,
        source,
      };
      Object.assign(ep, summary(ep, data.public));
      if (editEpisode) {
        hidden.push(editEpisode.id);
        episodes = episodes.filter((x) => x.id !== editEpisode.id);
        generated = generated.filter((x) => x.id !== editEpisode.id);
        for (const k of runs.keys())
          if (k.startsWith(editEpisode.id + ":")) runs.delete(k);
      }
      episodes.push(ep);
      generated.push(ep);
      cache.set(ep.id, data.public);
      save();
      el("generator-form").hidden = true;
      el("generated-result").hidden = false;
      el("generated-title").textContent = "Эпизод создан генератором команды";
      el("generated-description").textContent = preset + " · seed " + seed;
      el("generated-open").onclick = () => choose(ep.id, "investigation");
      await choose(ep.id, "episodes");
    } catch (error) {
      el("generator-error").textContent = error.message;
    } finally {
      busy = false;
      render();
    }
  };
  el("delete-cancel").onclick = () => el("delete-dialog").close();
  el("delete-confirm").onclick = () => {
    if (!deletion) return;
    const ids =
      deletion.kind === "company"
        ? episodes.filter((e) => e.companyId === deletion.id).map((e) => e.id)
        : [deletion.id];
    hidden.push(...ids);
    episodes = episodes.filter((e) => !ids.includes(e.id));
    generated = generated.filter((e) => !ids.includes(e.id));
    for (const id of ids) {
      cache.delete(id);
      for (const k of runs.keys()) if (k.startsWith(id + ":")) runs.delete(k);
      for (const k of Object.keys(confirmations))
        if (k.startsWith(id + ":")) delete confirmations[k];
    }
    if (deletion.kind === "company")
      companies = companies.filter((c) => c.id !== deletion.id);
    save();
    el("delete-dialog").close();
    el("generated-result").hidden = true;
    deletion = null;
    if (ids.includes(selected?.id)) choose(episodes[0]?.id, page);
    else render();
  };
  async function init() {
    render();
    status("Подключаемся к API команды…");
    try {
      const [index, config] = await Promise.all([
        api("/api/episodes"),
        api("/api/presets"),
      ]);
      presets = config.presets;
      el("generator-preset").innerHTML = options(
        presets.map((p) => [p, p]),
        "mixed_small",
      );
      episodes = index.episodes
        .map((ep) => ({
          id: ep.split + "/" + ep.name,
          companyId: "team-" + ep.split + "/" + ep.name,
          source: { split: ep.split, name: ep.name },
          counts: ep.counts,
          base: ep.base_currency,
          period: ep.period_start,
        }))
        .filter((e) => !hidden.includes(e.id));
      for (const ep of index.episodes) {
        const id = "team-" + ep.split + "/" + ep.name;
        if (
          !companies.some((c) => c.id === id) &&
          !hidden.includes(ep.split + "/" + ep.name)
        )
          companies.push({
            id,
            name: ep.company_name,
            sector: "Командный эпизод · " + ep.split,
          });
      }
      episodes.push(
        ...generated.filter((e) => companies.some((c) => c.id === e.companyId)),
      );
      save();
      await choose(episodes[0]?.id);
      status("API подключён · " + episodes.length + " эпизодов");
    } catch (e) {
      status(
        "API недоступен: " +
          e.message +
          ". Обновите страницу для повторного подключения.",
        true,
      );
    }
  }
  init();
})();
