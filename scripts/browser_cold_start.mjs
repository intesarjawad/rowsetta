import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir, loadavg } from "node:os";
import { join } from "node:path";
import { parseArgs } from "node:util";
import { setTimeout as delay } from "node:timers/promises";

const { values, positionals } = parseArgs({
  options: {
    runs: { type: "string", default: "5" },
    path: { type: "string", default: "both" },
    "allow-heavy-load": { type: "boolean", default: false },
  },
  allowPositionals: true,
});
const [url, output] = positionals;
const runs = Number(values.runs);
if (!url || !output || !Number.isInteger(runs) || runs < 1)
  throw new Error(
    "Usage: browser_cold_start.mjs [--runs 5] [--path both|auto|lite] URL OUTPUT",
  );
if (!["both", "auto", "lite"].includes(values.path))
  throw new Error("Unknown browser path");
const require = createRequire(
  new URL("../frontend/package.json", import.meta.url),
);
const { chromium, expect } = require("@playwright/test");
const executable =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ??
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser";
const downloadBytesPerSecond = 50_000_000 / 8;
const maxLoad = 8;
const results = [];

async function waitForLoad() {
  while (!values["allow-heavy-load"] && loadavg()[0] > maxLoad) {
    console.log(
      `Waiting for one-minute load <= ${maxLoad}: ${loadavg().join(", ")}`,
    );
    await delay(30_000);
  }
}

async function measure(context, visit, run, requestedPath) {
  const page = context.pages()[0];
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: 40,
    downloadThroughput: downloadBytesPerSecond,
    uploadThroughput: 10_000_000 / 8,
  });
  const responses = [];
  const largeTransfers = [];
  let manifestSha256;
  const transfers = { runtime: 0, weights: 0, ort: 0, page: 0 };
  const count = (response) =>
    responses.push(
      response.finished().then(async () => {
        const sizes = await response.request().sizes();
        const path = new URL(response.url()).pathname;
        if (path.endsWith("/browser/manifest.json"))
          manifestSha256 = createHash("sha256")
            .update(await response.body())
            .digest("hex");
        if (sizes.responseBodySize >= 5_000_000) {
          const seconds = response.request().timing().responseEnd / 1000;
          largeTransfers.push({
            asset: path,
            bytes: sizes.responseBodySize,
            seconds,
            bytes_per_second: sizes.responseBodySize / seconds,
          });
        }
        const category = path.includes("/browser/weights/")
          ? "weights"
          : path.includes("/browser/ort/")
            ? "ort"
            : path.includes("/browser/") &&
                !path.endsWith("/demo.json") &&
                !path.endsWith("/manifest.json")
              ? "runtime"
              : "page";
        transfers[category] += Math.max(0, sizes.responseBodySize);
      }),
    );
  context.on("response", count);
  const loads = [{ seconds: 0, averages: loadavg() }];
  const start = performance.now();
  const sample = () =>
    loads.push({
      seconds: (performance.now() - start) / 1000,
      averages: loadavg(),
    });
  const sampler = setInterval(sample, 1000);
  try {
    await page.goto(url);
    const cells = page.getByRole("table").locator("tbody").getByRole("button");
    await expect(cells.first()).toHaveText("Unlabelled", { timeout: 180_000 });
    let currentPage = 0;
    let tableSeconds;
    for (const [row, key] of [
      [0, "1"],
      [1, "1"],
      [152, "3"],
      [153, "3"],
      [276, "2"],
      [277, "2"],
    ]) {
      const targetPage = Math.floor(row / 100);
      while (currentPage < targetPage) {
        await page.getByRole("button", { name: "Next page" }).click();
        currentPage++;
        await expect(page.getByRole("rowheader").first()).toHaveText(
          String(currentPage * 100),
        );
      }
      const cell = cells.nth(row % 100);
      await cell.focus();
      await page.keyboard.press(key);
      await expect(cell).toHaveText(/Labelled/);
      // A successful label verifies interactivity, beyond merely painting a table.
      tableSeconds ??= (performance.now() - start) / 1000;
    }
    await expect(page.getByRole("status")).toHaveText("Proposals updated", {
      timeout: 180_000,
    });
    await expect(cells.filter({ hasText: /^Proposed / }).first()).toBeVisible();
    const firstProposalsSeconds = (performance.now() - start) / 1000;
    sample();
    const teacher = await page.locator("header.appbar > span").textContent();
    const path = teacher?.includes("TabICLv2 (WebGPU)")
      ? "tabiclv2"
      : teacher?.includes("lite model")
        ? "lite"
        : null;
    if (path === null || (requestedPath === "lite" && path !== "lite"))
      throw new Error(`Unexpected teacher: ${teacher}`);
    const webgpuAvailable = await page.evaluate(async () =>
      Boolean(await navigator.gpu?.requestAdapter()),
    );
    if (requestedPath === "auto" && webgpuAvailable && path !== "tabiclv2")
      throw new Error(
        "WebGPU is available but the shipping TabICLv2 path did not run",
      );
    await page.waitForLoadState("networkidle");
    await Promise.all(responses);
    if (
      visit === "warm" &&
      transfers.runtime + transfers.weights + transfers.ort !== 0
    )
      throw new Error(
        `Warm visit fetched cached assets: ${JSON.stringify(transfers)}`,
      );
    const bytes = Object.values(transfers).reduce((a, b) => a + b, 0);
    if (
      visit === "cold" &&
      (transfers.runtime === 0 ||
        (path === "tabiclv2" && transfers.weights === 0))
    )
      throw new Error(
        "Cold worker downloads were not observed by the benchmark",
      );
    if (
      (visit === "cold" &&
        bytes / firstProposalsSeconds > downloadBytesPerSecond) ||
      largeTransfers.some(
        (transfer) => transfer.bytes_per_second > downloadBytesPerSecond,
      )
    )
      throw new Error(
        `Worker transfer exceeded the 50 Mbit/s throttle: ${JSON.stringify(largeTransfers)}`,
      );
    return {
      run,
      measurement_scope: values["allow-heavy-load"]
        ? "heavy-load diagnostic"
        : "launch",
      requested_path: requestedPath,
      webgpu_available: webgpuAvailable,
      path,
      visit,
      table_seconds: tableSeconds,
      first_proposals_seconds: firstProposalsSeconds,
      bytes,
      executable,
      user_agent: await page.evaluate(() => navigator.userAgent),
      worker_url: page.workers().map((worker) => worker.url()),
      manifest_sha256: manifestSha256,
      large_transfers: largeTransfers,
      transfers,
      load_average: {
        start: loads[0].averages,
        end: loads.at(-1).averages,
        max: [0, 1, 2].map((index) =>
          Math.max(...loads.map((sample) => sample.averages[index])),
        ),
      },
    };
  } catch (error) {
    sample();
    if (
      values["allow-heavy-load"] ||
      !loads.some((sample) => sample.averages[0] > maxLoad)
    )
      throw error;
    console.log(
      `Failed under high load; retrying ${requestedPath} ${visit}: ${error}`,
    );
    return null;
  } finally {
    clearInterval(sampler);
    context.off("response", count);
    await cdp.detach();
  }
}

for (const requestedPath of values.path === "both"
  ? ["auto", "lite"]
  : [values.path]) {
  for (let run = 1; run <= runs;) {
    await waitForLoad();
    const profile = await mkdtemp(join(tmpdir(), "rowsetta-browser-cold-"));
    const options = {
      headless: false,
      executablePath: executable,
      // Exercise the real no-adapter branch without changing the shipping application.
      args:
        requestedPath === "lite" ? ["--disable-features=WebGPUService"] : [],
    };
    try {
      const pair = [];
      for (const visit of ["cold", "warm"]) {
        await waitForLoad();
        console.log(`Starting ${requestedPath} run ${run}/${runs}, ${visit}`);
        const context = await chromium.launchPersistentContext(
          profile,
          options,
        );
        try {
          const timing = await measure(context, visit, run, requestedPath);
          if (timing === null) break;
          pair.push(timing);
        } finally {
          await context.close();
        }
        if (
          !values["allow-heavy-load"] &&
          pair.at(-1).load_average.max[0] > maxLoad
        )
          break;
      }
      if (
        pair.length !== 2 ||
        (!values["allow-heavy-load"] &&
          pair.some((value) => value.load_average.max[0] > maxLoad))
      ) {
        console.log(
          `Discarding ${requestedPath} run ${run}: load exceeded ${maxLoad}`,
        );
        continue;
      }
      results.push(...pair);
      await writeFile(output, JSON.stringify(results, null, 2));
      console.log(JSON.stringify(pair));
      run++;
    } finally {
      await rm(profile, { recursive: true });
    }
  }
}
