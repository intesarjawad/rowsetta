declare module '*onnxruntime-web/dist/ort.bundle.min.mjs' {
  const env: import('../../node_modules/.pnpm/node_modules/onnxruntime-common').Env;
  const InferenceSession: typeof import('../../node_modules/.pnpm/node_modules/onnxruntime-common').InferenceSession;
  export { env, InferenceSession };
}
