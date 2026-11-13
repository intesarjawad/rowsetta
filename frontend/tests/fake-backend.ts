import type { Backend } from '../src/backend/http';
import type { ServerEvent, WorkspaceState } from '../src/backend/types';

function unused(): never {
  throw new Error('not used by this test');
}

// Serves `/state` from a queue and lets the test push server events; `routes`
// replaces the other requests a test makes.
export function fakeBackend(
  states: (() => Promise<WorkspaceState>)[],
  routes: Partial<Backend> = {},
) {
  let listener: ((event: ServerEvent) => void) | undefined;
  let stopped = false;
  const backend: Backend = {
    state: () => {
      const next = states.shift();
      if (next === undefined) throw new Error('unexpected /state request');
      return next();
    },
    loadDemo: unused,
    uploadCsv: unused,
    tablePage: unused,
    setTarget: unused,
    setLabel: unused,
    undo: unused,
    nextEvalRow: unused,
    setExcluded: unused,
    setThreshold: unused,
    distill: unused,
    audit: unused,
    suspects: unused,
    exportRule: unused,
    health: unused,
    session: unused,
    events: (follow) => {
      listener = follow;
      return () => {
        stopped = true;
      };
    },
    ...routes,
  };
  return {
    backend,
    send: (event: ServerEvent) => {
      if (listener === undefined) throw new Error('not following events');
      listener(event);
    },
    stopped: () => stopped,
    remaining: () => states.length,
  };
}
