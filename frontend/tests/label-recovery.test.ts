import { beforeEach, expect, test, vi } from 'vitest';
import { LabelRecovery } from '../src/browser/labels.svelte';

const session = (sha256 = 'a'.repeat(64), target = 'species') =>
  JSON.stringify({
    source: { sha256 },
    target,
    classes: ['a', 'b'],
    human: { '0': 'a' },
    eval: { '2': 'b' },
    eval_served: [2],
    undo_history: [{ row_id: 0, previous: null }],
  });
let storage: Map<string, string>;
beforeEach(() => {
  storage = new Map();
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  });
});

test('offers human and evaluation labels only for the same table hash and target', () => {
  const recovery = new LabelRecovery();
  recovery.save(session());
  recovery.offer(session('b'.repeat(64)));
  expect(recovery.pending).toBeNull();
  recovery.offer(session(undefined, 'another target'));
  expect(recovery.pending).toBeNull();
  recovery.offer(session());
  expect(recovery.pending?.count).toBe(2);
  expect(JSON.parse(recovery.pending?.session ?? '{}')).toMatchObject({
    human: { '0': 'a' },
    eval: { '2': 'b' },
    eval_served: [2],
    undo_history: [],
  });
});

test('does not overwrite saved labels on target selection; discard deletes them', () => {
  const recovery = new LabelRecovery();
  recovery.save(session());
  recovery.offer(session());
  recovery.save(session().replace('"human":{"0":"a"}', '"human":{}'));
  recovery.offer(session());
  expect(recovery.pending?.count).toBe(2);
  recovery.discard();
  recovery.offer(session());
  expect(recovery.pending).toBeNull();
  expect(storage.size).toBe(0);
});

test('persists clears and reports blocked, full or corrupted storage visibly', () => {
  const recovery = new LabelRecovery();
  recovery.save(session());
  recovery.save(
    session()
      .replace('"human":{"0":"a"}', '"human":{}')
      .replace('"eval":{"2":"b"}', '"eval":{}'),
  );
  recovery.offer(session());
  expect(recovery.pending).toBeNull();
  vi.stubGlobal('localStorage', {
    setItem: () => {
      throw new Error('Quota exceeded');
    },
    getItem: () => '{broken',
  });
  recovery.save(session());
  expect(recovery.problem).toContain('could not be saved');
  recovery.offer(session());
  expect(recovery.problem).toContain('could not be read');
});
