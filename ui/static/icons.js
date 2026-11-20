/* Lucide icons, ISC license, https://lucide.dev/license */
(() => {
  const icons = {
    "layout-dashboard": [
      ["rect", { width: "7", height: "9", x: "3", y: "3", rx: "1" }],
      ["rect", { width: "7", height: "5", x: "14", y: "3", rx: "1" }],
      ["rect", { width: "7", height: "9", x: "14", y: "12", rx: "1" }],
      ["rect", { width: "7", height: "5", x: "3", y: "16", rx: "1" }],
    ],
    "building-2": [
      ["path", { d: "M10 12h4" }],
      ["path", { d: "M10 8h4" }],
      ["path", { d: "M14 21v-3a2 2 0 0 0-4 0v3" }],
      [
        "path",
        {
          d: "M6 10H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2",
        },
      ],
      ["path", { d: "M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16" }],
    ],
    layers: [
      [
        "path",
        {
          d: "M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z",
        },
      ],
      [
        "path",
        {
          d: "M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12",
        },
      ],
      [
        "path",
        {
          d: "M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17",
        },
      ],
    ],
    "scan-search": [
      ["path", { d: "M3 7V5a2 2 0 0 1 2-2h2" }],
      ["path", { d: "M17 3h2a2 2 0 0 1 2 2v2" }],
      ["path", { d: "M21 17v2a2 2 0 0 1-2 2h-2" }],
      ["path", { d: "M7 21H5a2 2 0 0 1-2-2v-2" }],
      ["circle", { cx: "12", cy: "12", r: "3" }],
      ["path", { d: "m16 16-1.9-1.9" }],
    ],
    "git-compare-arrows": [
      ["circle", { cx: "5", cy: "6", r: "3" }],
      ["path", { d: "M12 6h5a2 2 0 0 1 2 2v7" }],
      ["path", { d: "m15 9-3-3 3-3" }],
      ["circle", { cx: "19", cy: "18", r: "3" }],
      ["path", { d: "M12 18H7a2 2 0 0 1-2-2V9" }],
      ["path", { d: "m9 15 3 3-3 3" }],
    ],
    "file-chart-column": [
      [
        "path",
        {
          d: "M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z",
        },
      ],
      ["path", { d: "M14 2v5a1 1 0 0 0 1 1h5" }],
      ["path", { d: "M8 18v-1" }],
      ["path", { d: "M12 18v-6" }],
      ["path", { d: "M16 18v-3" }],
    ],
    play: [
      [
        "path",
        {
          d: "M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z",
        },
      ],
    ],
    "arrow-right": [
      ["path", { d: "M5 12h14" }],
      ["path", { d: "m12 5 7 7-7 7" }],
    ],
  };
  for (const placeholder of document.querySelectorAll("[data-lucide]")) {
    const nodes = icons[placeholder.dataset.lucide];
    if (!nodes) continue;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    for (const [k, v] of Object.entries({
      viewBox: "0 0 24 24",
      width: 18,
      height: 18,
      fill: "none",
      stroke: "currentColor",
      "stroke-width": 1.5,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "aria-hidden": true,
      "data-lucide": placeholder.dataset.lucide,
    })) {
      svg.setAttribute(k, v);
    }
    for (const [tag, attrs] of nodes) {
      const node = document.createElementNS(svg.namespaceURI, tag);
      for (const [k, v] of Object.entries(attrs))
        if (k !== "key") node.setAttribute(k, v);
      svg.append(node);
    }
    placeholder.replaceWith(svg);
  }
})();
