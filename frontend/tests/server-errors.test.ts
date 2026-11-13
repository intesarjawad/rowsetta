import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it, vi } from 'vitest';
import checkServerErrors from '../e2e/server-errors';

it('fails the browser run when either server logged an unhandled error', () => {
  const directory = mkdtempSync(join(tmpdir(), 'rowsetta-errors-'));
  vi.stubEnv('ROWSETTA_E2E_SESSIONS', directory);
  try {
    writeFileSync(join(directory, 'main.errors.log'), '');
    writeFileSync(join(directory, 'slow-refit.errors.log'), '');
    expect(checkServerErrors).not.toThrow();
    writeFileSync(
      join(directory, 'slow-refit.errors.log'),
      'Request failed\n_DeadlockError',
    );
    expect(checkServerErrors).toThrow('Request failed\n_DeadlockError');
  } finally {
    vi.unstubAllEnvs();
    rmSync(directory, { recursive: true });
  }
});
