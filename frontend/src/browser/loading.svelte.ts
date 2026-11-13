import { LITE_MODEL } from './config';
export const runtimeLoading = $state({
  done: 0,
  total: 0,
  ready: false,
  model: 'Checking WebGPU support',
  fullModel: false,
  modelDone: 0,
  modelTotal: 0,
});
export function teacherName(fullModel: boolean): string {
  return fullModel ? 'TabICLv2 (WebGPU)' : LITE_MODEL;
}
