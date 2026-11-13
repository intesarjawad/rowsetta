import type { WorkspaceState } from './backend/types';
import type { Studio } from './state.svelte';

const NO_TABLE: WorkspaceState = {
  loaded: false,
  notice: null,
  target: null,
  classes: [],
  human: {},
  eval_count: 0,
  threshold: 0.6,
  excluded_columns: [],
  generation: 0,
  refit_generation: null,
  proposals: {},
  confidence: {},
  abstained: [],
  missing: {},
  next_row: null,
  evaluation: null,
  failure: null,
  dev_states: true,
};

const REFIT_DELAY_MS = 1200;

/**
 * Put a studio into a state the demo server cannot hold still, for design
 * review at `/?state=<name>` in the dev server. Never part of a production build.
 */
export function applyFixture(studio: Studio, name: string): void {
  switch (name) {
    case 'empty':
      studio.workspace = NO_TABLE;
      break;
    case 'error':
      studio.workspace = NO_TABLE;
      studio.problem = {
        error: 'That file has no rows to label.',
        next_step: 'Open a CSV with a header line and at least one row.',
      };
      break;
    case 'refit':
      studio.start();
      setTimeout(() => {
        studio.refit = { done: 3, total: 8 };
      }, REFIT_DELAY_MS);
      break;
    default:
      break;
  }
}
