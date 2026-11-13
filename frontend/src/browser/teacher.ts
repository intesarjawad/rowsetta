// forecast-web owns this runtime dependency; use pnpm's shared copy so its env is shared.
import {
  env,
  InferenceSession,
} from '../../node_modules/.pnpm/node_modules/onnxruntime-web/dist/ort.bundle.min.mjs';
import {
  loadTabular,
  type Cell,
  type LoadTabularOptions,
} from 'forecast-web/tabular';

// shortcut: forecast-web has no session options; remove this adapter when it exposes logging.
InferenceSession.create = new Proxy(
  InferenceSession.create.bind(InferenceSession),
  {
    apply(create, receiver: unknown, args: unknown[]) {
      const index = typeof args[1] === 'number' ? 3 : 1;
      const options = args[index];
      args[index] = {
        ...(typeof options === 'object' && options !== null ? options : {}),
        logSeverityLevel: 3,
      };
      const session: unknown = Reflect.apply(create, receiver, args);
      return session;
    },
  },
);

// Bound prediction shapes: the large WebGPU batch fails parity (ADR 0003).
export const PREDICT_BATCH_ROWS = 500;

export async function loadTeacher(
  weights: string,
  nEstimators: number,
  options: Pick<LoadTabularOptions, 'wasmPaths' | 'onProgress'> = {},
) {
  env.logLevel = 'error';
  const model = await loadTabular({
    task: 'classification',
    weights,
    nEstimators,
    randomState: 7,
    dtype: 'fp16',
    device: 'webgpu',
    worker: false,
    // The worker verifies cached weight bytes; forecast-web skips cached checks.
    cache: false,
    ...options,
  });
  return {
    backend: model.backend,
    dispose: () => model.dispose(),
    fit(train: Cell[][], labels: (string | number)[]) {
      const fitted = model.fit(train, labels);
      return {
        classes: fitted.classes,
        async predictProba(rows: Cell[][]): Promise<number[][]> {
          const probabilities: number[][] = [];
          for (
            let start = 0;
            start < rows.length;
            start += PREDICT_BATCH_ROWS
          ) {
            probabilities.push(
              ...(await fitted.predictProba(
                rows.slice(start, start + PREDICT_BATCH_ROWS),
              )),
            );
          }
          return probabilities;
        },
      };
    },
  };
}
