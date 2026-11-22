const { chromium } = require("playwright");
const fs = require("node:fs"),
  path = require("node:path"),
  assert = require("node:assert/strict");
(async () => {
  const b = await chromium.launch({
    headless: true,
    ...(process.env.CHROME_PATH
      ? { executablePath: process.env.CHROME_PATH }
      : {}),
  });
  try {
    const p = await b.newPage({
      viewport: { width: 1440, height: 1000 },
      acceptDownloads: true,
    });
    const errors = [],
      checks = [];
    p.on("pageerror", (e) => errors.push(e.message));
    const ok = (name, result) => {
      assert(result, name);
      checks.push(name);
    };
    await p.goto(process.env.BASE_URL);
    await p.waitForFunction(() =>
      document
        .querySelector("#ag-status")
        .textContent.includes("Данные загружены"),
    );
    ok(
      "real API data",
      await p
        .locator("#ag-company")
        .textContent()
        .then((t) => t === "Zhetysu Consulting Ltd"),
    );
    ok(
      "no external white border",
      await p.evaluate(
        () =>
          getComputedStyle(document.body).margin === "0px" &&
          getComputedStyle(document.body).backgroundColor === "rgb(238, 243, 246)",
      ),
    );
    await p.locator("#ag-theme").click();
    ok(
      "dark theme toggle",
      await p.evaluate(
        () =>
          document.documentElement.dataset.theme === "dark" &&
          getComputedStyle(document.body).backgroundColor === "rgb(8, 15, 28)" &&
          localStorage.getItem("auditgym.theme") === "dark",
      ),
    );
    await p.reload();
    await p.waitForFunction(
      () =>
        document.documentElement.dataset.theme === "dark" &&
        document.querySelector("#ag-status").textContent.includes("Данные загружены"),
    );
    await p.locator("#ag-theme").click();
    ok(
      "light theme toggle",
      await p.evaluate(
        () => getComputedStyle(document.body).backgroundColor === "rgb(238, 243, 246)",
      ),
    );
    ok("icons loaded", (await p.locator(".ag-navigation svg").count()) === 6);
    for (const page of [
      "overview",
      "companies",
      "episodes",
      "investigation",
      "comparison",
      "reports",
    ]) {
      await p.locator(".ag-navigation [data-page=" + page + "]").click();
      ok("navigation " + page, await p.locator("#ag-" + page).isVisible());
    }
    await p.locator(".ag-navigation [data-page=overview]").click();
    await p.locator("#ag-run").click();
    await p.waitForFunction(() =>
      document
        .querySelector("#ag-status")
        .textContent.includes("Проверка завершена"),
    );
    ok(
      "native policy findings",
      (await p.locator("#ag-findings tr").count()) === 6,
    );
    ok(
      "actual trajectory",
      await p
        .locator("#ag-step-count")
        .textContent()
        .then((t) => t.endsWith("/ 17")),
    );
    await p.locator("#ag-confirm").click();
    ok(
      "manual confirmation",
      await p
        .locator("#ag-confirm")
        .textContent()
        .then((t) => t.includes("подтверждён")),
    );
    await p.locator(".ag-navigation [data-page=overview]").click();
    await p.locator("#ag-filter").selectOption("fx_conversion");
    ok(
      "real discrepancy type filter",
      (await p.locator("#ag-findings tr").count()) === 2,
    );
    await p.locator("#ag-filter").selectOption("all");
    await p.locator("#ag-search").fill("PAY-GVW5XE");
    ok("document search", (await p.locator("#ag-findings tr").count()) === 3);
    await p.locator("#ag-search").fill("");
    for (let i = 0; i < 6; i++) {
      await p.locator(".ag-navigation [data-page=overview]").click();
      await p.locator('[data-finding="' + i + '"]').click();
      const ids = await p.locator("[data-evidence]").count();
      for (let j = 0; j < ids; j++) {
        await p.locator("[data-evidence]").nth(j).click();
        ok(
          "public evidence " + i + "/" + j,
          await p
            .locator("#ag-proof-detail")
            .textContent()
            .then((t) => !t.includes("не найдена")),
        );
      }
    }
    await p.locator(".ag-navigation [data-page=overview]").click();
    await p.locator('[data-finding="0"]').click();
    await p.locator("#ag-prev").click();
    ok(
      "real previous step",
      await p
        .locator("#ag-step-count")
        .textContent()
        .then((t) => t.startsWith("16")),
    );
    await p.locator("#ag-next").click();
    await p.locator("[data-evidence]").first().click();
    ok(
      "evidence public document",
      await p
        .locator("#ag-proof-detail")
        .textContent()
        .then(
          (t) =>
            t.includes("invoice_id") ||
            t.includes("payment_id") ||
            t.includes("row_id"),
        ),
    );
    await p.locator(".ag-navigation [data-page=reports]").click();
    await p.locator("#ag-report-scope").selectOption("confirmed");
    ok(
      "confirmed report filter",
      (await p.locator("#ag-report-findings tr").count()) === 1,
    );
    for (const format of ["txt", "csv", "json"]) {
      await p.locator("#ag-report-format").selectOption(format);
      const dl = p.waitForEvent("download");
      await p.locator("#ag-report-download").click();
      const d = await dl;
      const content = fs.readFileSync(await d.path(), "utf8");
      ok("download " + format, content.length > 100);
      if (format === "json") {
        const report = JSON.parse(content);
        ok(
          "real grader report",
          report.metrics.f1 === 1 &&
            report.findings.length === 1 &&
            report.findings[0].manually_confirmed === true,
        );
      }
    }
    await p.locator(".ag-navigation [data-page=comparison]").click();
    await p.locator("#ag-run").click();
    await p.waitForFunction(() => !document.querySelector("#ag-run").disabled);
    ok(
      "four actual policy scores",
      await p
        .locator("#ag-agent-list td.ag-number")
        .allTextContents()
        .then((xs) => !xs.includes("—") && xs.length === 20),
    );
    await p.locator("[data-agent=Oracle]").click();
    ok(
      "Oracle privilege label",
      await p
        .locator("#ag-agent-description")
        .textContent()
        .then((t) => t.includes("Привилегированный")),
    );
    await p.locator("[data-agent=Reconciler]").click();
    await p.locator(".ag-navigation [data-page=companies]").click();
    await p.locator("#ag-new-company").click();
    await p.locator("#ag-company-name").fill("<bad>");
    await p.locator("#ag-company-form [type=submit]").click();
    ok(
      "company validation",
      await p.locator("#ag-company-error").textContent().then(Boolean),
    );
    await p.locator("#ag-company-name").fill("Тест API");
    await p.locator("#ag-company-form [type=submit]").click();
    let card = p
      .locator("#ag-company-cards section")
      .filter({ hasText: "Тест API" });
    ok("create company", (await card.count()) === 1);
    await card.locator("[data-edit-company]").click();
    await p.locator("#ag-company-name").fill("Тест API изменён");
    await p.locator("#ag-company-form [type=submit]").click();
    card = p
      .locator("#ag-company-cards section")
      .filter({ hasText: "Тест API изменён" });
    ok("edit company", (await card.count()) === 1);
    await card.locator("[data-generate]").click();
    await p.locator("#ag-generator-preset").selectOption("mixed_small");
    await p.locator("#ag-generator-seed").fill("42");
    await p.locator("#ag-generator-form [type=submit]").click();
    await p.locator("#ag-generated-result").waitFor({ state: "visible" });
    await p.locator("#ag-generated-open").click();
    await p.waitForFunction(
      () => document.querySelector("#ag-run").disabled === false,
    );
    ok(
      "generated real documents",
      (await p.locator("#ag-records tr").count()) === 40,
    );
    await p.locator("#ag-run").click();
    await p.waitForFunction(() =>
      document
        .querySelector("#ag-status")
        .textContent.includes("Проверка завершена"),
    );
    ok(
      "generated real run",
      await p
        .locator("#ag-findings tr")
        .count()
        .then((n) => n > 0),
    );
    await p.locator(".ag-navigation [data-page=episodes]").click();
    let row = p
      .locator("#ag-episode-list tr")
      .filter({ hasText: "Тест API изменён" });
    await row.locator("[data-edit-episode]").click();
    await p.locator("#ag-generator-seed").fill("43");
    await p.locator("#ag-generator-form [type=submit]").click();
    await p.waitForFunction(
      () => document.querySelector("#ag-generator-form").hidden,
    );
    ok(
      "edit regenerates episode",
      await row.textContent().then((t) => t.includes("43")),
    );
    await row.locator("[data-delete-episode]").click();
    ok("delete confirmation", await p.locator("#ag-delete-dialog").isVisible());
    await p.locator("#ag-delete-cancel").click();
    ok("cancel delete", (await row.count()) === 1);
    await row.locator("[data-delete-episode]").click();
    await p.locator("#ag-delete-confirm").click();
    ok(
      "delete episode",
      (await p
        .locator("#ag-episode-list tr")
        .filter({ hasText: "Тест API изменён" })
        .count()) === 0,
    );
    await p.locator(".ag-navigation [data-page=companies]").click();
    card = p
      .locator("#ag-company-cards section")
      .filter({ hasText: "Тест API изменён" });
    await card.locator("[data-delete-company]").click();
    await p.locator("#ag-delete-confirm").click();
    ok(
      "delete company",
      (await p
        .locator("#ag-company-cards section")
        .filter({ hasText: "Тест API изменён" })
        .count()) === 0,
    );
    await p.reload();
    await p.waitForFunction(() =>
      document
        .querySelector("#ag-status")
        .textContent.includes("Данные загружены"),
    );
    await p.locator(".ag-navigation [data-page=companies]").click();
    ok(
      "catalog persists on reload",
      (await p
        .locator("#ag-company-cards section")
        .filter({ hasText: "Тест API изменён" })
        .count()) === 0,
    );
    for (const width of [320, 768, 1440]) {
      await p.setViewportSize({ width, height: 1000 });
      for (const name of [
        "overview",
        "companies",
        "episodes",
        "investigation",
        "comparison",
        "reports",
      ]) {
        await p.locator(".ag-navigation [data-page=" + name + "]").click();
        ok(
          "width " + width + " " + name,
          await p.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        );
      }
    }
    await p.setViewportSize({ width: 1440, height: 1000 });
    await p.locator(".ag-navigation [data-page=overview]").click();
    await p.locator("#ag-run").click();
    await p.waitForFunction(() =>
      document
        .querySelector("#ag-status")
        .textContent.includes("Проверка завершена"),
    );
    await p.locator(".ag-navigation [data-page=overview]").click();
    await p.screenshot({ path: "runs/web-ui-qa.png", fullPage: true });
    ok("no JavaScript errors", errors.length === 0);
    fs.writeFileSync(
      "runs/web-ui-qa.json",
      JSON.stringify({ status: "passed", checks, errors }, null, 2),
    );
    console.log(
      JSON.stringify({ status: "passed", checks: checks.length, errors }),
    );
  } finally {
    await b.close();
  }
})().catch((e) => {
  console.error(e.stack);
  process.exitCode = 1;
});
