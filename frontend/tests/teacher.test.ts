import {
  env,
  InferenceSession,
} from '../node_modules/.pnpm/node_modules/onnxruntime-web/dist/ort.bundle.min.mjs';
import { expect, test, vi } from 'vitest';
import { loadTeacher } from '../src/browser/teacher';

const mocks = vi.hoisted(() => ({
  predict: vi.fn((rows: unknown[][]) =>
    Promise.resolve(rows.map(() => [0.25, 0.75])),
  ),
  load: vi.fn(),
  env: { logLevel: 'warning' },
  create: vi.fn().mockResolvedValue({}),
}));
vi.mock('forecast-web/tabular', () => ({ loadTabular: mocks.load }));
vi.mock(
  '../node_modules/.pnpm/node_modules/onnxruntime-web/dist/ort.bundle.min.mjs',
  () => ({ env: mocks.env, InferenceSession: { create: mocks.create } }),
);

test('uses the native seed and bounds each WebGPU prediction batch', async () => {
  const fit = vi.fn(() => ({
    classes: ['a', 'b'],
    predictProba: mocks.predict,
  }));
  mocks.load.mockResolvedValue({ backend: 'webgpu', fit, dispose: vi.fn() });
  env.logLevel = 'warning';
  const teacher = await loadTeacher('/weights', 4);
  expect(env.logLevel).toBe('error');
  const fitted = teacher.fit([[1], [2]], ['a', 'b']);
  const rows = Array.from({ length: 2000 }, (_, i) => [i]);
  const probabilities = await fitted.predictProba(rows);
  expect(mocks.load).toHaveBeenCalledWith(
    expect.objectContaining({ randomState: 7, cache: false }),
  );
  expect(mocks.predict.mock.calls.map(([batch]) => batch.length)).toEqual([
    500, 500, 500, 500,
  ]);
  expect(mocks.predict.mock.calls.flatMap(([batch]) => batch)).toEqual(rows);
  expect(probabilities).toEqual(rows.map(() => [0.25, 0.75]));
  expect(fitted.classes).toEqual(['a', 'b']);
});

test('keeps unsupported WebGPU implementations on the lite fallback', async () => {
  const { supportsBrowserTeacher } = await import('../src/browser/config');
  expect(
    supportsBrowserTeacher('Mozilla/5.0 Chrome/142.0.0.0 Safari/537.36'),
  ).toBe(true);
  expect(
    supportsBrowserTeacher('Mozilla/5.0 Chrome/142.0.0.0 Edg/142.0.0.0'),
  ).toBe(true);
  expect(
    supportsBrowserTeacher('Mozilla/5.0 Version/26.0 Safari/605.1.15'),
  ).toBe(false);
  expect(supportsBrowserTeacher('Mozilla/5.0 Firefox/145.0')).toBe(false);
  expect(
    supportsBrowserTeacher('Mozilla/5.0 CriOS/142.0.0.0 Mobile Safari/604.1'),
  ).toBe(false);
});

test('keeps actual model load failures visible to the caller', async () => {
  mocks.load.mockRejectedValueOnce(new Error('Model failed'));
  await expect(loadTeacher('/weights', 4)).rejects.toThrow('Model failed');
});

test('sets error severity on ORT sessions without dropping provider or buffer options', async () => {
  const bytes = new Uint8Array([1, 2, 3]);
  await InferenceSession.create(bytes, { executionProviders: ['webgpu'] });
  expect(mocks.create).toHaveBeenLastCalledWith(bytes, {
    executionProviders: ['webgpu'],
    logSeverityLevel: 3,
  });
  await InferenceSession.create(bytes.buffer, 1, 2, {
    executionProviders: ['wasm'],
  });
  expect(mocks.create).toHaveBeenLastCalledWith(bytes.buffer, 1, 2, {
    executionProviders: ['wasm'],
    logSeverityLevel: 3,
  });
  mocks.create.mockRejectedValueOnce(new Error('ORT failed'));
  await expect(InferenceSession.create(bytes)).rejects.toThrow('ORT failed');
});
