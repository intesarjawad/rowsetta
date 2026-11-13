import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(resolve("frontend/package.json"));
const { chromium } = require("@playwright/test");
const root = resolve(".");
const scratch = await mkdtemp(join(tmpdir(), "rowsetta-demo-"));
const port = 18873;
const origin = `http://${"127.0.0.1"}:${port}`;
const token = "recording-session";
const csv = join(scratch, "penguins-mislabelled.csv");
const run = (command, args) => {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit" });
  if (result.status !== 0)
    throw new Error(`${command} failed (${result.status})`);
};
run("uv", ["run", "--locked", "python", "scripts/mislabel_demo.py", csv]);
const server = spawn(
  "uv",
  [
    "run",
    "--locked",
    "rowsetta",
    "open",
    csv,
    "--no-browser",
    "--port",
    String(port),
  ],
  {
    cwd: root,
    env: {
      ...process.env,
      ROWSETTA_SESSION_TOKEN: token,
      ROWSETTA_SESSIONS_DIR: join(scratch, "sessions"),
      ROWSETTA_TEACHER: "",
    },
    stdio: "ignore",
  },
);
const headers = {
  Cookie: `rowsetta_session_${new URL(origin).port}=${token}`,
  "Content-Type": "application/json",
};
async function request(path, options = {}) {
  const response = await fetch(`${origin}${path}`, { ...options, headers });
  if (!response.ok)
    throw new Error(
      `${path}: HTTP ${response.status}: ${await response.text()}`,
    );
  return response.json();
}
async function waitFor(test, timeout = 900_000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (await test()) return;
    await new Promise((done) => setTimeout(done, 1000));
  }
  throw new Error("Timed out waiting for the local model");
}
let browser;
try {
  await waitFor(async () => {
    try {
      return (await fetch(`${origin}/health`)).ok;
    } catch {
      return false;
    }
  }, 60_000);
  const classes = ["Adelie", "Chinstrap", "Gentoo"];
  const truth = (await readFile("src/rowsetta/datasets/penguins.csv", "utf8"))
    .trim()
    .split("\n")
    .slice(1)
    .map((line) => line.split(",")[0]);
  await request("/target", {
    method: "POST",
    body: JSON.stringify({ target: "species", classes }),
  });
  browser = await chromium.launch({
    executablePath:
      "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    headless: true,
  });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
  });
  await context.addCookies([
    { name: `rowsetta_session_${new URL(origin).port}`, value: token, url: origin },
  ]);
  const page = await context.newPage();
  let holdState = false;
  let releaseState;
  let stateRequested;
  const stateGate = new Promise((resolve) => {
    releaseState = resolve;
  });
  const stateQueued = new Promise((resolve) => {
    stateRequested = resolve;
  });
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/events") return route.continue();
    const path = url.pathname;
    if (path === "/state" && holdState) {
      stateRequested();
      await stateGate;
    }
    try {
      const response = await route.fetch({
        url: `${origin}${path}${url.search}`,
        timeout: 900_000,
      });
      await route.fulfill({ response });
    } catch {
      throw new Error(`Request failed for ${path}`);
    }
  });
  async function settled() {
    let latest;
    await waitFor(async () => {
      latest = await request("/state");
      if (latest.failure) throw new Error(JSON.stringify(latest.failure));
      return latest.refit_generation === latest.generation;
    });
    return latest;
  }
  async function openPage() {
    await page.goto(`${origin}/`, {
      waitUntil: "domcontentloaded",
    });
    await page.evaluate(() => {
      document.documentElement.style.zoom = "0.8888889";
    });
    await page
      .getByRole("table")
      .waitFor({ state: "visible", timeout: 60_000 });
    await page.evaluate(() => {
      const caption = document.createElement("div");
      caption.id = "recording-caption";
      caption.style.cssText =
        "position:fixed;z-index:9999;bottom:18px;left:50%;transform:translateX(-50%);background:#111;color:#fff;padding:12px 20px;border-radius:4px;font:700 23px system-ui,sans-serif;white-space:nowrap;box-shadow:0 2px 8px #0004";
      document.body.append(caption);
      const model = document.createElement("div");
      model.textContent = "TabICLv2 · local model";
      model.style.cssText =
        "position:fixed;z-index:9999;bottom:8px;right:8px;background:#111;color:#fff;padding:6px 10px;font:600 14px system-ui,sans-serif";
      document.body.append(model);
    });
  }
  let frame = 0;
  async function caption(text) {
    await page.locator("#recording-caption").evaluate((el, value) => {
      el.textContent = value;
    }, text);
  }
  async function frames(count) {
    for (let i = 0; i < count; i++) {
      const started = Date.now();
      await page.screenshot({
        path: join(scratch, `frame-${String(frame++).padStart(4, "0")}.png`),
      });
      await page.waitForTimeout(Math.max(0, 67 - (Date.now() - started)));
    }
  }
  await openPage();
  await page
    .getByRole("table")
    .evaluate((el) => el.scrollIntoView({ block: "start" }));
  const labels = [
    [0, "1"],
    [1, "1"],
    [152, "3"],
    [153, "3"],
    [276, "2"],
    [277, "2"],
  ];
  await caption(
    `Label ${labels.length} rows you have checked. Keep a SQL rule for the rest.`,
  );
  let tablePage = 0;
  for (const [row, key] of labels) {
    const targetPage = Math.floor(row / 100);
    while (tablePage < targetPage) {
      await page.getByRole("button", { name: "Next page" }).click();
      tablePage++;
      await page.waitForFunction(
        (expected) =>
          document.querySelector("tbody th")?.textContent?.trim() ===
          String(expected),
        tablePage * 100,
      );
    }
    const cell = page
      .getByRole("table")
      .locator("tbody")
      .getByRole("button")
      .nth(row % 100);
    await cell.focus();
    if (row === labels.at(-1)[0]) holdState = true;
    await page.keyboard.press(key);
    await cell.getByText(/Labelled/).waitFor({ timeout: 30_000 });
    await frames(5);
  }
  const proposed = await settled();
  const abstained = new Set(proposed.abstained);
  const suggestions = Object.keys(proposed.proposals).filter(
    (row) => !(row in proposed.human) && !abstained.has(Number(row)),
  ).length;
  if (Object.keys(proposed.human).length !== labels.length || suggestions === 0)
    throw new Error("Teaching did not produce proposals from six labels");
  await Promise.race([
    stateQueued,
    new Promise((_, reject) =>
      setTimeout(
        () => reject(new Error("State refresh did not arrive")),
        30_000,
      ).unref(),
    ),
  ]);
  await caption(
    `The model suggests ${suggestions} labels; the rest remain unsure.`,
  );
  holdState = false;
  releaseState();
  await frames(20);
  const panel = page.getByRole("region", { name: "Accuracy" });
  await panel.getByRole("button", { name: "Evaluate (e)" }).click();
  const served = panel.getByText(/^Evaluating row \d+:/);
  await caption("Check random rows without seeing a proposal.");
  for (let index = 0; index < 20; index++) {
    await served.waitFor({ state: "attached", timeout: 60_000 });
    const match = (await served.textContent())?.match(/Evaluating row (\d+):/);
    if (!match) throw new Error("Evaluation row was not shown");
    const row = Number(match[1]);
    const key = classes.indexOf(truth[row]) + 1;
    if (key === 0) throw new Error(`Missing truth for row ${row}`);
    const cell = page
      .getByRole("table")
      .locator("tbody tr")
      .filter({
        has: page.getByRole("rowheader", { name: String(row), exact: true }),
      })
      .getByRole("button");
    await cell.waitFor({ state: "visible", timeout: 60_000 });
    await cell.press(String(key));
    await page.waitForFunction(
      (previous) => {
        const text =
          document.querySelector(".panel--eval .hint")?.textContent ?? "";
        return !text.includes(`Evaluating row ${previous}:`);
      },
      row,
      { timeout: 60_000 },
    );
    if ((index + 1) % 4 === 0) await frames(4);
  }
  const evaluated = await settled();
  if (evaluated.evaluation?.n !== 20)
    throw new Error("Twenty evaluation rows were not measured");
  await openPage();
  await panel.evaluate((el) => el.scrollIntoView({ block: "center" }));
  const pct = (value) => `${Math.round(value * 100)}%`;
  await caption(
    `Checked on ${evaluated.evaluation.n} random rows: ${pct(evaluated.evaluation.accuracy.value)} vs ${pct(evaluated.evaluation.majority_baseline)} guessing.`,
  );
  await frames(10);
  await request("/target", {
    method: "POST",
    body: JSON.stringify({ target: "species" }),
  });
  await settled();
  await openPage();
  const list = page.getByRole("list", { name: "Labels the model doubts most" });
  await list.waitFor({ state: "visible", timeout: 900_000 });
  const first = list.getByRole("listitem").first().getByRole("button").first();
  await first.waitFor({ state: "visible" });
  await page.waitForTimeout(1500);
  const sqlResponse = await fetch(
    `${origin}/export?format=sql&dialect=duckdb`,
    { headers },
  );
  const sql = await sqlResponse.text();
  const certificate = sql
    .split("\n")
    .filter((line) => /^-- (Cross-fitted agreement|Execution:)/.test(line))
    .map((line) => line.slice(3));
  if (
    !sqlResponse.ok ||
    !sql.includes("-- tabicl version:") ||
    certificate.length !== 2 ||
    !certificate[1].includes("DuckDB")
  )
    throw new Error("Missing agreement or DuckDB execution certificate");
  await page
    .locator("#interchange")
    .evaluate((el) => el.scrollIntoView({ block: "start" }));
  await caption(
    "Audit existing labels: review each disagreement with the teacher.",
  );
  if ((await first.getAttribute("aria-expanded")) === "true")
    await first.click();
  await page.waitForTimeout(250);
  await first.click();
  await frames(35);
  await page.getByRole("button", { name: "Export rule", exact: true }).click();
  await page
    .locator(".certificate")
    .waitFor({ state: "visible", timeout: 900_000 });
  await page
    .locator(".certificate")
    .evaluate((el) => el.scrollIntoView({ block: "center" }));
  await caption(certificate.join("\n"));
  await page.locator("#recording-caption").evaluate((el) => {
    el.style.fontSize = "20px";
    el.style.whiteSpace = "pre";
  });
  await frames(5);
  await page
    .locator("pre")
    .first()
    .evaluate((el) => {
      // Frame the exported query; its certificate remains in the caption.
      const sql = el.textContent;
      const offset = sql.indexOf("SELECT");
      if (offset < 0) throw new Error("SQL SELECT is missing");
      el.textContent = sql.slice(offset);
      el.style.cssText +=
        "position:fixed;inset:64px 24px 112px;z-index:9998;margin:0;max-height:none;font-size:18px;line-height:1.35;white-space:pre-wrap;overflow-wrap:anywhere;overflow:auto";
      el.scrollTop = 0;
      if (el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight)
        throw new Error("Closing SQL does not fit the frame");
    });
  await frames(38);
  await context.close();
  const filter =
    "fps=15,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=96[p];[s1][p]paletteuse=dither=bayer";
  run("ffmpeg", [
    "-hide_banner",
    "-loglevel",
    "error",
    "-y",
    "-framerate",
    "15",
    "-i",
    join(scratch, "frame-%04d.png"),
    "-filter_complex",
    filter,
    "docs/demo.gif",
  ]);
  const bytes = (await stat("docs/demo.gif")).size;
  const probe = spawnSync(
    "ffprobe",
    [
      "-v",
      "error",
      "-show_entries",
      "format=duration",
      "-of",
      "csv=p=0",
      "docs/demo.gif",
    ],
    { encoding: "utf8" },
  );
  if (probe.status !== 0) throw new Error("Could not read GIF duration");
  const duration = Number(probe.stdout.trim());
  if (bytes >= 8_000_000) throw new Error(`GIF exceeds 8 MB: ${bytes} bytes`);
  console.log(
    `Recorded docs/demo.gif: ${bytes} bytes, 960 px, ${duration.toFixed(2)} seconds`,
  );
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
  await rm(scratch, { recursive: true, force: true });
}
