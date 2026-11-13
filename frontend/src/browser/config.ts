export const BROWSER = import.meta.env.MODE === 'browser';
export const BROWSER_ASSETS = `${import.meta.env.BASE_URL}browser/`;
export const LITE_MODEL = 'lite model (random forest), not TabICLv2';

// ORT's WebGPU provider supports Chromium; an adapter alone is insufficient (ADR 0007).
export function supportsBrowserTeacher(userAgent: string): boolean {
  return /\b(?:Chrome|Chromium)\/\d+/.test(userAgent);
}
