import { loadPyodide, type PyodideInterface } from 'pyodide';
import { loadTeacher } from './teacher';
import { predictRefit } from './refit';
import { supportsBrowserTeacher } from './config';

async function pythonText(py: PyodideInterface, code: string): Promise<string> {
  const value: unknown = await py.runPythonAsync(code);
  if (typeof value !== 'string') throw new Error('Invalid Python response');
  return value;
}

interface Command {
  id: number;
  message: string;
}
interface Start {
  base: string;
  today: string;
}
interface Asset {
  bytes: number;
  sha256: string;
}

function manifest(value: unknown): Record<string, Asset> {
  if (typeof value !== 'object' || value === null)
    throw new Error('Invalid runtime manifest');
  const entries: Record<string, Asset> = {};
  const unknownEntries: Record<string, unknown> = Object.fromEntries(
    Object.entries(value),
  );
  for (const [name, entry] of Object.entries(unknownEntries)) {
    if (
      typeof entry !== 'object' ||
      entry === null ||
      !('bytes' in entry) ||
      typeof entry.bytes !== 'number' ||
      !('sha256' in entry) ||
      typeof entry.sha256 !== 'string'
    )
      throw new Error('Invalid runtime asset');
    entries[name] = { bytes: entry.bytes, sha256: entry.sha256 };
  }
  return entries;
}

async function start({ base, today }: Start) {
  const network = globalThis.fetch.bind(globalThis);
  const response = await network(`${base}manifest.json`);
  if (!response.ok)
    throw new Error('Cannot load the runtime manifest. Reload this page.');
  const assets = manifest(await response.json());
  const cache = await caches.open('rowsetta-browser-v1');
  const isModel = (name: string) =>
    name.startsWith('weights/') || name.startsWith('ort/');
  const total = Object.entries(assets).reduce(
    (sum, [name, asset]) => sum + (isModel(name) ? 0 : asset.bytes),
    0,
  );
  let done = 0;
  const counted = new Set<string>();
  // Pyodide's fetches consume only bytes verified against the build manifest,
  // including cache hits. A corrupt hit is discarded and fetched again.
  const download: typeof fetch = async (input, init) => {
    const url = new URL(
      input instanceof Request ? input.url : input.toString(),
      base,
    ).href;
    const asset = assets[url.slice(base.length)];
    if (!url.startsWith(base) || asset === undefined)
      throw new Error(`Unexpected runtime request: ${url}`);
    async function verified(source: Response): Promise<Response | null> {
      const bytes = await source.arrayBuffer();
      const digest = Array.from(
        new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
        (n) => n.toString(16).padStart(2, '0'),
      ).join('');
      if (bytes.byteLength !== asset?.bytes || digest !== asset.sha256)
        return null;
      return new Response(bytes, { headers: source.headers });
    }
    const saved = await cache.match(url);
    let result = saved === undefined ? null : await verified(saved);
    if (result === null) {
      if (saved !== undefined) await cache.delete(url);
      const fresh = await network(url, init);
      if (!fresh.ok)
        throw new Error(`Download failed (${String(fresh.status)}): ${url}`);
      result = await verified(fresh);
      if (result === null) throw new Error(`Runtime checksum mismatch: ${url}`);
      await cache.put(url, result.clone());
    }
    if (!isModel(url.slice(base.length)) && !counted.has(url)) {
      counted.add(url);
      done += asset.bytes;
    }
    postMessage({ kind: 'loading', done, total });
    return result;
  };
  // Emscripten can leave startup pending after a failed WASM fetch.
  globalThis.fetch = (input, init) =>
    download(input, init).catch((error: unknown) => {
      postMessage({
        kind: 'fatal',
        error: error instanceof Error ? error.message : String(error),
      });
      throw error;
    });
  postMessage({ kind: 'loading', done, total });
  const browserNavigator: { gpu?: GPU } = navigator;
  const adapter = supportsBrowserTeacher(navigator.userAgent)
    ? ((await browserNavigator.gpu?.requestAdapter()) ?? null)
    : null;
  const model = adapter
    ? loadTeacher(`${base}weights`, 4, {
        wasmPaths: `${base}ort/`,
        onProgress: (progress) => {
          postMessage({ kind: 'model-loading', progress });
        },
      })
    : Promise.resolve(null);
  // Observe model failures while runtime packages are still loading.
  void model.catch((error: unknown) => {
    postMessage({ kind: 'fatal', error: String(error) });
  });
  postMessage({
    kind: 'teacher',
    fullModel: adapter !== null,
  });
  const py = await loadPyodide({ indexURL: `${base}runtime/` });
  await py.loadPackage([
    'numpy',
    'pandas',
    'scipy',
    'scikit-learn',
    'pydantic',
    'micropip',
  ]);
  await py.runPythonAsync(`
import micropip
await micropip.install(${JSON.stringify(`${base}rowsetta_browser_core-0.1.0-py3-none-any.whl`)}, deps=False)
from rowsetta.browser_shell import BrowserShell, browser_metadata
from rowsetta.core.lite_teacher import LiteTeacher
browser = BrowserShell(${adapter ? 'None' : 'LiteTeacher()'}, browser_metadata(${JSON.stringify(today)}, full_model=${adapter ? 'True' : 'False'}))
`);
  const csvResponse = await fetch(`${base}penguins.csv`);
  const csv = await csvResponse.text();
  await py.runPythonAsync(`
browser.workspace.load(${JSON.stringify(csv)}.encode(), 'penguins.csv', max_rows=2000)
browser.workspace.set_target('species', ('Adelie', 'Chinstrap', 'Gentoo'))
`);
  const teacher = await model;
  if (teacher !== null && teacher.backend !== 'webgpu')
    throw new Error('Expected the WebGPU teacher');
  postMessage({
    kind: 'labels',
    session: await pythonText(
      py,
      'browser.workspace.require_store().to_json()',
    ),
    save: false,
  });
  postMessage({ kind: 'ready' });
  return { py, teacher };
}

let runtime: ReturnType<typeof start> | undefined;
let commands = Promise.resolve();
onmessage = (event: MessageEvent<Start | Command>) => {
  const data = event.data;
  if ('base' in data) {
    // WebKit on Linux can miss the wake-up when its engine finishes a WebAssembly
    // compile on another thread, so the promise stays pending while the worker
    // idles. A running timer turns the worker loop, which delivers the result.
    const pulse = setInterval(() => undefined, 50);
    runtime = start(data).finally(() => {
      clearInterval(pulse);
    });
    void runtime.catch((error: unknown) => {
      postMessage({
        kind: 'fatal',
        error: error instanceof Error ? error.message : String(error),
      });
    });
    return;
  }
  const started = runtime;
  commands = commands.then(async () => {
    try {
      if (started === undefined) throw new Error('Runtime has not started');
      const { py, teacher } = await started;
      const input: unknown = JSON.parse(data.message);
      const restoring =
        typeof input === 'object' &&
        input !== null &&
        'action' in input &&
        input.action === 'restore' &&
        'session' in input &&
        typeof input.session === 'string';
      if (restoring) {
        await py.runPythonAsync(`
from rowsetta.core.session import LabelStore
saved_labels = LabelStore.from_json(${JSON.stringify(input.session)})
current_source = browser.workspace.require_store().source
if saved_labels.source.sha256 != current_source.sha256 or saved_labels.source.row_ids() != current_source.row_ids() or saved_labels.target != browser.workspace.require_store().target:
    raise ValueError('Saved labels belong to another table or target')
browser.workspace.set_target(saved_labels.target, saved_labels.classes)
browser.workspace.store = saved_labels
browser.workspace.invalidate()
`);
      }
      const message = restoring
        ? JSON.stringify({ action: 'state' })
        : data.message;
      let value: unknown = await py.runPythonAsync(
        `browser.call(${JSON.stringify(message)}, refit=${teacher === null ? 'True' : 'False'})`,
      );
      if (typeof value !== 'string') throw new Error('Invalid Python response');
      let response: unknown = JSON.parse(value);
      if (
        typeof response === 'object' &&
        response !== null &&
        'ok' in response &&
        response.ok === true &&
        typeof input === 'object' &&
        input !== null &&
        'action' in input
      ) {
        if (input.action === 'load') postMessage({ kind: 'table-loaded' });
        else if (
          [
            'target',
            'label',
            'undo',
            'exclude',
            'threshold',
            'restore',
            'eval',
          ].includes(String(input.action))
        ) {
          postMessage({
            kind: 'labels',
            session: await pythonText(
              py,
              'browser.workspace.require_store().to_json()',
            ),
            save: input.action !== 'target',
          });
        }
        if (restoring) {
          if (teacher === null) await py.runPythonAsync('browser.refit()');
          const refit = await pythonText(py, 'browser.refit_input()');
          response = { ...response, refit };
          value = await py.runPythonAsync(`browser.call('{"action":"state"}')`);
        }
      }
      if (
        teacher !== null &&
        typeof response === 'object' &&
        response !== null &&
        'ok' in response &&
        response.ok === true &&
        'refit' in response &&
        typeof response.refit === 'string'
      ) {
        const result = await predictRefit(teacher, response.refit);
        if (result !== null) {
          await py.runPythonAsync(
            `browser.publish_refit(${JSON.stringify(result)})`,
          );
          value = await py.runPythonAsync(`browser.call('{"action":"state"}')`);
        }
      }
      postMessage({ kind: 'result', id: data.id, value });
    } catch {
      postMessage({
        kind: 'result',
        id: data.id,
        value: JSON.stringify({
          ok: false,
          error: {
            error: 'The browser runtime could not complete this operation.',
            next_step:
              'Try the operation again. To recover saved labels, reload this page and reopen the same CSV and target, then choose Restore labels.',
          },
        }),
      });
    }
  });
};
