/* Builds the audit report as a Word document (.docx) in the browser, without libraries.
 * window.auditgymDocx(model) -> Blob. A .docx is a ZIP of WordprocessingML parts; the ZIP is
 * written uncompressed ("stored"), which Word, LibreOffice and Pages all open. */
(() => {
  "use strict";
  const ACCENT = "087F80",
    INK = "172C38",
    SUB = "617581",
    LINE = "D5E0E4",
    SOFT = "E6F5F2",
    ZEBRA = "F5F8FA",
    FONT = "Arial";

  const xml = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  // ---- WordprocessingML helpers -------------------------------------------------------------
  function run(text, o = {}) {
    const props =
      (o.mono
        ? '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>'
        : `<w:rFonts w:ascii="${FONT}" w:hAnsi="${FONT}" w:cs="${FONT}"/>`) +
      (o.bold ? "<w:b/>" : "") +
      (o.caps ? "<w:caps/>" : "") +
      (o.color ? `<w:color w:val="${o.color}"/>` : "") +
      (o.size ? `<w:sz w:val="${o.size}"/><w:szCs w:val="${o.size}"/>` : "") +
      (o.spacing ? `<w:spacing w:val="${o.spacing}"/>` : "") +
      "";
    return String(text ?? "")
      .split("\n")
      .map((line, i) => `<w:r>${props ? `<w:rPr>${props}</w:rPr>` : ""}${i ? "<w:br/>" : ""}<w:t xml:space="preserve">${xml(line)}</w:t></w:r>`)
      .join("");
  }
  function para(content, o = {}) {
    const props =
      (o.style ? `<w:pStyle w:val="${o.style}"/>` : "") +
      (o.keepNext ? "<w:keepNext/>" : "") +
      (o.border ? `<w:pBdr><w:bottom w:val="single" w:sz="8" w:space="6" w:color="${o.border}"/></w:pBdr>` : "") +
      `<w:spacing w:before="${o.before ?? 0}" w:after="${o.after ?? 80}"/>` +
      (o.align ? `<w:jc w:val="${o.align}"/>` : "");
    return `<w:p><w:pPr>${props}</w:pPr>${typeof content === "string" ? content : run(content.text, content)}</w:p>`;
  }
  function cell(content, o = {}) {
    const borders = o.noBorder
      ? '<w:tcBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/><w:right w:val="nil"/></w:tcBorders>'
      : "";
    const body = Array.isArray(content) ? content.join("") : content;
    return (
      `<w:tc><w:tcPr><w:tcW w:w="${o.width}" w:type="dxa"/>${borders}` +
      (o.fill ? `<w:shd w:val="clear" w:color="auto" w:fill="${o.fill}"/>` : "") +
      `<w:tcMar><w:top w:w="${o.pad ?? 90}" w:type="dxa"/><w:bottom w:w="${o.pad ?? 90}" w:type="dxa"/>` +
      '<w:left w:w="140" w:type="dxa"/><w:right w:w="140" w:type="dxa"/></w:tcMar>' +
      `<w:vAlign w:val="${o.valign || "top"}"/></w:tcPr>${body || "<w:p/>"}</w:tc>`
    );
  }
  function table(widths, rows, o = {}) {
    const total = widths.reduce((a, b) => a + b, 0);
    const b = o.borders === false
      ? '<w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/><w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/>'
      : `<w:top w:val="single" w:sz="4" w:color="${LINE}"/><w:left w:val="nil"/><w:bottom w:val="single" w:sz="4" w:color="${LINE}"/><w:right w:val="nil"/><w:insideH w:val="single" w:sz="4" w:color="${LINE}"/><w:insideV w:val="nil"/>`;
    return (
      `<w:tbl><w:tblPr><w:tblW w:w="${total}" w:type="dxa"/><w:tblLayout w:type="fixed"/>` +
      `<w:tblBorders>${b}</w:tblBorders>` +
      (o.cellSpacing ? `<w:tblCellSpacing w:w="${o.cellSpacing}" w:type="dxa"/>` : "") +
      `</w:tblPr><w:tblGrid>${widths.map((w) => `<w:gridCol w:w="${w}"/>`).join("")}</w:tblGrid>` +
      rows
        .map(
          (r) =>
            `<w:tr><w:trPr><w:cantSplit/>${r.header ? "<w:tblHeader/>" : ""}</w:trPr>` +
            r.cells.map((c, i) => cell(c.content, { width: widths[i], ...r.cellOptions, ...c })).join("") +
            "</w:tr>",
        )
        .join("") +
      "</w:tbl>"
    );
  }
  const small = (text, o = {}) => para({ text, size: 17, color: SUB, ...o }, { after: 20, ...o.p });

  // ---- Document body ------------------------------------------------------------------------
  function body(m) {
    const W = 14570; // A4 landscape text width (16838 - 2 × 1134)
    const parts = [];
    parts.push(para({ text: "auditgym · аудит расчётов с покупателями", size: 17, color: ACCENT, bold: true, caps: true, spacing: 20 }, { after: 120 }));
    parts.push(para({ text: m.title, size: 40, bold: true, color: INK }, { after: 60 }));
    parts.push(para({ text: m.subtitle, size: 24, color: SUB }, { after: 240, border: ACCENT }));

    // Details: two label/value pairs per row.
    const details = m.details;
    const rows = [];
    for (let i = 0; i < details.length; i += 2) {
      const pair = details.slice(i, i + 2);
      while (pair.length < 2) pair.push(["", ""]);
      rows.push({
        cells: pair.flatMap(([k, v]) => [
          { content: small(k) },
          { content: para({ text: v, size: 20, color: INK, bold: true }, { after: 0 }) },
        ]),
      });
    }
    parts.push(table([2000, 5285, 2000, 5285], rows.map((r) => ({ ...r, cellOptions: { pad: 50, noBorder: true } })), { borders: false }));

    // Summary cards.
    parts.push(para({ text: "Итоги проверки", size: 28, bold: true, color: INK }, { before: 320, after: 140, keepNext: true }));
    const cw = Math.floor(W / m.metrics.length);
    parts.push(
      table(
        m.metrics.map(() => cw),
        [{
          cells: m.metrics.map(([label, value, note]) => ({
            content: [
              small(label),
              para({ text: value, size: 40, bold: true, color: ACCENT }, { after: 20 }),
              note ? small(note) : "",
            ],
            fill: SOFT,
            pad: 160,
          })),
        }],
        { borders: false, cellSpacing: 60 },
      ),
    );
    if (m.verdict) parts.push(para({ text: m.verdict, size: 20, color: INK }, { before: 160, after: 0 }));

    // Findings.
    parts.push(para({ text: "Найденные расхождения", size: 28, bold: true, color: INK }, { before: 360, after: 140, keepNext: true }));
    if (m.findings.length) {
      const widths = [560, 2500, 2900, 2050, 4760, 1800];
      const head = ["№", "Тип", "Документы", "Сумма", "Доказательства", "Статус"];
      parts.push(
        table(widths, [
          {
            header: true,
            cells: head.map((h, i) => ({
              content: para({ text: h, size: 18, bold: true, color: "FFFFFF" }, { after: 0, align: i === 3 ? "right" : undefined }),
              fill: ACCENT,
            })),
          },
          ...m.findings.map((f, n) => ({
            cellOptions: n % 2 ? { fill: ZEBRA } : {},
            cells: [
              { content: para({ text: String(n + 1), size: 19, color: SUB }, { after: 0 }) },
              { content: para({ text: f.type, size: 19, bold: true, color: INK }, { after: 0 }) },
              { content: para({ text: f.documents, size: 18, mono: true, color: INK }, { after: 0 }) },
              { content: para({ text: f.amount, size: 19, bold: true, color: INK }, { after: 0, align: "right" }) },
              { content: para({ text: f.evidence, size: 17, color: SUB }, { after: 0 }) },
              { content: para({ text: f.status, size: 18, bold: f.confirmed, color: f.confirmed ? ACCENT : "9A6A12" }, { after: 0 }) },
            ],
          })),
        ]),
      );
    } else {
      parts.push(table([W], [{ cells: [{ content: para({ text: m.emptyText, size: 20, color: INK }, { after: 0 }), fill: SOFT, pad: 200 }] }], { borders: false }));
    }

    // Type explanations.
    if (m.hints.length) {
      parts.push(para({ text: "Что означают типы расхождений", size: 28, bold: true, color: INK }, { before: 360, after: 120, keepNext: true }));
      for (const [name, hint] of m.hints)
        parts.push(para(run(name + ". ", { bold: true, size: 19, color: INK }) + run(hint, { size: 19, color: INK }), { after: 80 }));
    }

    parts.push(para({ text: m.footnote, size: 16, color: SUB }, { before: 360, after: 0 }));
    return parts.join("");
  }

  function documentXml(m) {
    return (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
      `<w:body>${body(m)}<w:sectPr><w:footerReference w:type="default" r:id="rId2"/>` +
      '<w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>' +
      '<w:pgMar w:top="1000" w:right="1134" w:bottom="1000" w:left="1134" w:header="500" w:footer="500" w:gutter="0"/>' +
      "</w:sectPr></w:body></w:document>"
    );
  }
  function footerXml(m) {
    const field = (code) =>
      `<w:r><w:rPr><w:color w:val="${SUB}"/><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>` +
      `<w:r><w:rPr><w:color w:val="${SUB}"/><w:sz w:val="16"/></w:rPr><w:instrText xml:space="preserve"> ${code} </w:instrText></w:r>` +
      `<w:r><w:rPr><w:color w:val="${SUB}"/><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="separate"/></w:r>` +
      `<w:r><w:rPr><w:color w:val="${SUB}"/><w:sz w:val="16"/></w:rPr><w:t>1</w:t></w:r>` +
      `<w:r><w:rPr><w:color w:val="${SUB}"/><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>`;
    return (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
      `<w:p><w:pPr><w:pBdr><w:top w:val="single" w:sz="4" w:space="6" w:color="${LINE}"/></w:pBdr><w:tabs><w:tab w:val="right" w:pos="14570"/></w:tabs></w:pPr>` +
      run(m.footer, { size: 16, color: SUB }) +
      `<w:r><w:tab/></w:r>` + run("Стр. ", { size: 16, color: SUB }) + field("PAGE") + run(" из ", { size: 16, color: SUB }) + field("NUMPAGES") +
      "</w:p></w:ftr>"
    );
  }
  const STYLES =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
    `<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="${FONT}" w:hAnsi="${FONT}" w:eastAsia="${FONT}" w:cs="${FONT}"/>` +
    `<w:color w:val="${INK}"/><w:sz w:val="20"/><w:szCs w:val="20"/><w:lang w:val="ru-RU"/></w:rPr></w:rPrDefault>` +
    '<w:pPrDefault><w:pPr><w:spacing w:after="80" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>' +
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>' +
    '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:tblPr><w:tblCellMar>' +
    '<w:left w:w="108" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style></w:styles>';

  function parts(m) {
    const now = new Date().toISOString().replace(/\.\d+Z$/, "Z");
    return {
      "[Content_Types].xml":
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>' +
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>' +
        '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>' +
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>',
      "_rels/.rels":
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>',
      "docProps/core.xml":
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' +
        `<dc:title>${xml(m.title + " — " + m.subtitle)}</dc:title><dc:creator>auditgym</dc:creator><dc:language>ru-RU</dc:language>` +
        `<dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created></cp:coreProperties>`,
      "word/_rels/document.xml.rels":
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/></Relationships>',
      "word/document.xml": documentXml(m),
      "word/styles.xml": STYLES,
      "word/footer1.xml": footerXml(m),
    };
  }

  // ---- Minimal ZIP writer (stored entries) --------------------------------------------------
  const CRC = new Uint32Array(256).map((_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  function crc32(bytes) {
    let c = 0xffffffff;
    for (const b of bytes) c = CRC[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }
  function zip(files) {
    const enc = new TextEncoder(),
      chunks = [],
      central = [];
    let offset = 0;
    for (const [name, text] of Object.entries(files)) {
      const nameBytes = enc.encode(name),
        data = enc.encode(text),
        crc = crc32(data);
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true);
      local.setUint16(4, 20, true);
      local.setUint16(8, 0, true); // stored
      local.setUint16(12, 0x21, true); // 1980-01-01, fixed for reproducible files
      local.setUint32(14, crc, true);
      local.setUint32(18, data.length, true);
      local.setUint32(22, data.length, true);
      local.setUint16(26, nameBytes.length, true);
      chunks.push(local.buffer, nameBytes, data);
      const dir = new DataView(new ArrayBuffer(46));
      dir.setUint32(0, 0x02014b50, true);
      dir.setUint16(4, 20, true);
      dir.setUint16(6, 20, true);
      dir.setUint16(14, 0x21, true);
      dir.setUint32(16, crc, true);
      dir.setUint32(20, data.length, true);
      dir.setUint32(24, data.length, true);
      dir.setUint16(28, nameBytes.length, true);
      dir.setUint32(42, offset, true);
      central.push(dir.buffer, nameBytes);
      offset += 30 + nameBytes.length + data.length;
    }
    const size = central.reduce((a, c) => a + c.byteLength, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, central.length / 2, true);
    end.setUint16(10, central.length / 2, true);
    end.setUint32(12, size, true);
    end.setUint32(16, offset, true);
    return new Blob([...chunks, ...central, end.buffer], {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
  }

  window.auditgymDocx = (model) => zip(parts(model));
})();
