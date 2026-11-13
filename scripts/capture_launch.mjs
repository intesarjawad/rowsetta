import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(resolve("frontend/package.json"));
const { chromium, expect } = require("@playwright/test");
const scratch = await mkdtemp(join(tmpdir(), "rowsetta-launch-"));
const origin = "http://127.0.0.1:18874";
const token = "launch-capture";
const csv = join(scratch, "penguins.csv");
async function run(command, args) {
  const child = spawn(command, args, { stdio: "inherit" });
  const code = await new Promise((done) => child.on("exit", done));
  if (code !== 0) throw new Error(`${command} exited ${code}`);
}
let server;
let browser;
try {
  await run("uv", [
    "run",
    "--locked",
    "python",
    "scripts/mislabel_demo.py",
    csv,
  ]);
  server = spawn(
    "uv",
    [
      "run",
      "--locked",
      "rowsetta",
      "open",
      csv,
      "--no-browser",
      "--port",
      "18874",
    ],
    {
      env: {
        ...process.env,
        ROWSETTA_SESSION_TOKEN: token,
        ROWSETTA_SESSIONS_DIR: join(scratch, "sessions"),
        ROWSETTA_TEACHER: "",
      },
      stdio: "inherit",
    },
  );
  const deadline = Date.now() + 60_000;
  for (;;) {
    try {
      if ((await fetch(`${origin}/health`)).ok) break;
    } catch {
      /* The server has not bound its port yet. */
    }
    if (Date.now() >= deadline) throw new Error("Capture server did not start");
    await new Promise((done) => setTimeout(done, 250));
  }
  const response = await fetch(`${origin}/target`, {
    method: "POST",
    headers: {
      Cookie: `rowsetta_session_${new URL(origin).port}=${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ target: "species" }),
  });
  if (!response.ok) throw new Error(`Target: HTTP ${response.status}`);
  browser = await chromium.launch({
    headless: true,
    executablePath:
      "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    reducedMotion: "reduce",
  });
  await context.addCookies([
    {
      name: `rowsetta_session_${new URL(origin).port}`,
      value: token,
      url: origin,
    },
  ]);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(origin);
  const doubts = page.getByRole("list", {
    name: "Labels the model doubts most",
  });
  await expect(doubts).toBeVisible({ timeout: 900_000 });
  const first = doubts
    .getByRole("listitem")
    .first()
    .getByRole("button")
    .first();
  await expect(first).toBeVisible({ timeout: 900_000 });
  if ((await first.getAttribute("aria-expanded")) !== "true")
    await first.click();
  await expect(first).toHaveAttribute("aria-expanded", "true");
  await page.evaluate(() => document.fonts.ready);
  for (const [name, width, height] of [
    ["hero", 1440, 900],
    ["social-preview", 1280, 640],
  ]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(
      (zoom) => {
        document.documentElement.style.zoom = zoom;
      },
      name === "hero" ? "0.8888889" : "0.8",
    );
    await expect(page.locator(".appbar")).toContainText("model up to date", {
      timeout: 900_000,
    });
    await expect(page.getByText(/wrong line|Fix all 9/)).toHaveCount(0);
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({ path: `docs/${name}.png`, animations: "disabled" });
    console.log(`Captured docs/${name}.png (${width}×${height})`);
  }
  const shots = process.env.ROWSETTA_FIX_SHOTS;
  if (shots !== undefined) {
    await mkdir(shots, { recursive: true });
    for (const [width, height] of [
      [1440, 900],
      [390, 844],
    ]) {
      await page.setViewportSize({ width, height });
      await page.evaluate(() => {
        document.documentElement.style.zoom = "1";
      });
      await page.evaluate(() => scrollTo(0, 0));
      await page.screenshot({
        path: join(shots, `rule-${width}x${height}.png`),
        animations: "disabled",
      });
    }
  }
  expect(errors).toEqual([]);
} finally {
  if (browser) await browser.close();
  if (server) server.kill("SIGTERM");
  await rm(scratch, { recursive: true, force: true });
}
