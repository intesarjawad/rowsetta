// Diagnostic copy only: production imports the pinned, patched package unchanged.
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
const require = createRequire(
  new URL("../frontend/package.json", import.meta.url),
);
const root = new URL("../frontend/public/spike/", import.meta.url);
const dist = join(
  dirname(require.resolve("forecast-web/package.json")),
  "dist",
);
let source = await readFile(join(dist, "tabular.js"), "utf8");
const boundary = "const outputs = await graph.run(feeds);";
if (!source.includes(boundary))
  throw new Error("Pinned inference boundary changed");
source = source.replaceAll('"./', '"/node_modules/forecast-web/dist/');
source = source.replace(
  boundary,
  `${boundary}
  opts.trace?.({norm, group, encoded: all.map(c => Array.from(c)),
    X: Array.from(Xd), dims: feeds.X.dims, y: Array.from(yd),
    logits: Array.from(outputs.logits),
    stages: Object.fromEntries(Object.entries(outputs).filter(([k]) => k !== 'logits').map(([k,v]) => [k,Array.from(v)]))});`,
);
await writeFile(new URL("instrumented.mjs", root), source);
const { chromium } = require("@playwright/test");
const browser = await chromium.launch({
  headless: false,
  executablePath:
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ??
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
  args: ["--enable-unsafe-webgpu"],
});
try {
  const page = await browser.newPage();
  await page.routeWebSocket("**", (socket) => socket.close());
  await page.goto(
    `${process.env.PARITY_URL ?? "http://127.0.0.1:5173"}/parity.html`,
  );
  page.on("console", (message) => {
    if (message.type() === "error") console.error(message.text());
  });
  const graph = process.argv.includes("--graph");
  const traces = await page.evaluate(async (graph) => {
    if (!(await navigator.gpu?.requestAdapter()))
      throw new Error("No WebGPU adapter");
    const { loadTabular } = await import("/spike/instrumented.mjs");
    const golden = await (await fetch("/spike/golden.json")).json();
    const results = [];
    for (const seed of graph ? [7] : [42, 7]) {
      const groups = [];
      const model = await loadTabular({
        task: "classification",
        weights: `${location.origin}/spike/${graph ? "debug-weights" : "weights"}`,
        dtype: graph ? "fp32" : "fp16",
        nEstimators: golden.estimators,
        randomState: seed,
        device: "webgpu",
        worker: false,
        cache: false,
        trace: (value) => groups.push(value),
      }).catch((e) => {
        console.error(String(e.cause));
        throw e;
      });
      if (model.backend !== "webgpu") throw new Error("Wrong backend");
      for (const dataset of golden.datasets.slice(0, 2)) {
        groups.length = 0;
        const probabilities = await model
          .fit(dataset.train, dataset.labels)
          .predictProba(dataset.test);
        results.push({
          name: dataset.name,
          seed,
          probabilities,
          traces: structuredClone(groups),
        });
      }
      await model.dispose();
    }
    return results;
  }, graph);
  const output = new URL(
    graph ? "graph-tensors.json" : "browser-tensors.json",
    root,
  );
  await writeFile(output, JSON.stringify(traces));
  console.log(output.pathname);
} finally {
  await browser.close();
}
