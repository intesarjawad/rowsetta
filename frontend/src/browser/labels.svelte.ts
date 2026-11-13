function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function record(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) throw new Error('Invalid saved labels');
  return value;
}

function savedSession(session: string) {
  const value = record(JSON.parse(session));
  const source = record(value.source);
  if (
    typeof source.sha256 !== 'string' ||
    !/^[a-f0-9]{64}$/.test(source.sha256) ||
    typeof value.target !== 'string'
  )
    throw new Error('Invalid saved label identity');
  const count =
    Object.keys(record(value.human)).length +
    Object.keys(record(value.eval)).length;
  return {
    key: `rowsetta.labels.v1:${JSON.stringify([source.sha256, value.target])}`,
    count,
    // Bound saved history to the working labels, rather than every past edit.
    session: JSON.stringify({ ...value, undo_history: [] }),
  };
}

/** Compact browser sessions stay on this origin; the worker validates them on restore. */
export class LabelRecovery {
  pending = $state.raw<ReturnType<typeof savedSession> | null>(null);
  problem = $state<string | null>(null);

  offer(session: string): void {
    this.pending = null;
    try {
      const current = savedSession(session);
      const stored = localStorage.getItem(current.key);
      if (stored === null) return;
      const saved = savedSession(stored);
      if (saved.key !== current.key)
        throw new Error('Saved table or target differs');
      if (saved.count > 0) this.pending = saved;
    } catch {
      this.problem =
        'Saved labels could not be read. Check browser storage permissions before reloading.';
    }
  }

  save(session: string): void {
    try {
      const saved = savedSession(session);
      if (this.pending?.key === saved.key) return;
      localStorage.setItem(saved.key, saved.session);
      this.problem = null;
    } catch {
      this.problem =
        'Labels could not be saved in this browser. Free browser storage or allow site storage before reloading.';
    }
  }

  discard(): void {
    if (this.pending === null) return;
    try {
      localStorage.removeItem(this.pending.key);
      this.pending = null;
      this.problem = null;
    } catch {
      this.problem =
        'Saved labels could not be discarded. Allow site storage and try again.';
    }
  }
}
