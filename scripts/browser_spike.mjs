import { createRequire } from "node:module";
import { writeFile } from "node:fs/promises";
const require = createRequire(
  new URL("../frontend/package.json", import.meta.url),
);
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
  page.on("pageerror", (error) => console.error(error.message));
  await page.goto(
    `${process.env.PARITY_URL ?? "http://127.0.0.1:5173"}/parity.html`,
  );
  await page.waitForFunction(() => typeof window.loadTeacher === "function");
  const result = await page.evaluate(async () => {
    const adapter = await navigator.gpu?.requestAdapter();
    if (!adapter)
      throw new Error(
        "A headed WebGPU adapter is required; refusing to time WASM",
      );
    const golden = await (await fetch("/spike/golden.json")).json();
    const model = await window.loadTeacher(
      `${location.origin}/spike/weights`,
      golden.estimators,
    );
    if (model.backend !== "webgpu")
      throw new Error(`Expected webgpu, got ${model.backend}`);
    const results = [];
    for (const dataset of golden.datasets) {
      const predict = async () => {
        const fitted = model.fit(dataset.train, dataset.labels);
        const order = dataset.classes.map((label) =>
          fitted.classes.indexOf(label),
        );
        if (order.some((index) => index < 0))
          throw new Error("Browser and Python classes differ");
        return (await fitted.predictProba(dataset.test)).map((row) =>
          order.map((index) => row[index]),
        );
      };
      const probabilities = await predict(); // Warm-up is also the parity run.
      if (
        probabilities.length !== dataset.probabilities.length ||
        probabilities.some(
          (row) =>
            row.length !== dataset.classes.length ||
            !row.every(Number.isFinite),
        )
      )
        throw new Error("Invalid probability shape or value");
      let maxDifference = 0,
        stableFlips = 0,
        nearTies = 0;
      for (let row = 0; row < probabilities.length; row++) {
        const actual = probabilities[row],
          expected = dataset.probabilities[row];
        for (let col = 0; col < actual.length; col++)
          maxDifference = Math.max(
            maxDifference,
            Math.abs(actual[col] - expected[col]),
          );
        const ranked = expected
          .map((value, index) => ({ value, index }))
          .sort((a, b) => b.value - a.value);
        const top = actual.indexOf(Math.max(...actual));
        if (ranked[0].value - ranked[1].value <= 0.004) nearTies++;
        else if (top !== ranked[0].index) stableFlips++;
      }
      const times = [];
      if (dataset.name !== "adult_2k")
        for (let i = 0; i < 5; i++) {
          const start = performance.now();
          await predict();
          times.push((performance.now() - start) / 1000);
        }
      results.push({
        name: dataset.name,
        rows: probabilities.length,
        labels: dataset.labels.length,
        maxDifference,
        stableFlips,
        nearTies,
        times,
        medianSeconds: times.length
          ? [...times].sort((a, b) => a - b)[2]
          : null,
      });
    }
    await model.dispose();
    return {
      estimators: golden.estimators,
      backend: model.backend,
      adapter: adapter.info,
      results,
    };
  });
  result.browserVersion = browser.version();
  await writeFile(
    process.argv[2] ?? "/tmp/rowsetta-browser-spike.json",
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result, null, 2));
  if (
    process.argv.includes("--assert") &&
    result.results.some((r) => r.maxDifference > 0.002 || r.stableFlips !== 0)
  )
    throw new Error("Browser parity gate failed");
} finally {
  await browser.close();
}
