import type { ByRow, WorkspaceState } from './backend/types';

/** Rows the table shows at once. */
export const PAGE_SIZE = 100;

/**
 * The teacher's last published answers. A label change clears them on the server
 * until the refit lands; the table keeps showing them, marked stale, meanwhile.
 */
export interface ShownProposals {
  target: string | null;
  labels: ByRow<string>;
  /** Rows whose confidence is below the threshold; their label is not shown. */
  unsure: ReadonlySet<number>;
  stale: boolean;
}

export const NO_PROPOSALS: ShownProposals = {
  target: null,
  labels: {},
  unsure: new Set(),
  stale: false,
};

/** Whether the state's proposals were fitted on its current inputs. */
export function isCurrent(workspace: WorkspaceState): boolean {
  return workspace.refit_generation === workspace.generation;
}

function needsLabels(workspace: WorkspaceState): boolean {
  return Object.keys(workspace.missing).length > 0;
}

export function nextProposals(
  shown: ShownProposals,
  workspace: WorkspaceState,
): ShownProposals {
  if (isCurrent(workspace)) {
    return {
      target: workspace.target,
      labels: workspace.proposals,
      unsure: new Set(workspace.abstained),
      stale: false,
    };
  }
  // No refit is coming for a new target or below the label minimum, so old
  // proposals would stay on screen as if one were.
  if (workspace.target !== shown.target || needsLabels(workspace)) {
    return { ...NO_PROPOSALS, target: workspace.target };
  }
  return { ...shown, stale: true };
}

/** What a row's label cell shows; the four kinds differ in text, not only in colour. */
export type RowLabel =
  | { kind: 'human'; label: string }
  | { kind: 'proposed'; label: string; stale: boolean }
  | { kind: 'unsure'; stale: boolean }
  | { kind: 'unlabelled' };

export function rowLabel(
  rowId: number,
  human: ByRow<string>,
  proposals: ShownProposals,
): RowLabel {
  const key = String(rowId);
  const labelled = human[key];
  if (labelled !== undefined) return { kind: 'human', label: labelled };
  if (proposals.unsure.has(rowId)) {
    return { kind: 'unsure', stale: proposals.stale };
  }
  const proposed = proposals.labels[key];
  if (proposed !== undefined) {
    return { kind: 'proposed', label: proposed, stale: proposals.stale };
  }
  return { kind: 'unlabelled' };
}

const STALE_SUFFIX = ', updating';

export function rowLabelText(state: RowLabel): string {
  switch (state.kind) {
    case 'human':
      return `Labelled ${state.label}`;
    case 'proposed':
      return `Proposed ${state.label}${state.stale ? STALE_SUFFIX : ''}`;
    case 'unsure':
      return `Unsure${state.stale ? STALE_SUFFIX : ''}`;
    case 'unlabelled':
      return 'Unlabelled';
  }
}

/** Human labels each class still needs before proposals start, as one sentence. */
export function missingText(missing: Readonly<Record<string, number>>): string {
  const needed = Object.entries(missing).map(
    ([label, count]) => `${String(count)} more ${label}`,
  );
  return needed.length === 0
    ? ''
    : `Proposals start after ${needed.join(', ')}.`;
}

export type TableCommand =
  | { kind: 'label'; classIndex: number }
  | { kind: 'move'; by: 1 | -1 }
  | { kind: 'undo' }
  | { kind: 'next' }
  | { kind: 'evaluate' }
  | { kind: 'keys' };

export type KeyPress = Pick<
  KeyboardEvent,
  'key' | 'altKey' | 'ctrlKey' | 'metaKey'
>;

// Keys 1 to 9 pick classes 1 to 9 and 0 picks class 10, in keyboard order.
const CLASS_KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'];

/** The table shortcut a key press means, or `null` so the browser handles it. */
export function tableCommand(press: KeyPress): TableCommand | null {
  if (press.altKey || press.ctrlKey || press.metaKey) return null;
  const classIndex = CLASS_KEYS.indexOf(press.key);
  if (classIndex !== -1) return { kind: 'label', classIndex };
  switch (press.key) {
    case 'j':
    case 'ArrowDown':
      return { kind: 'move', by: 1 };
    case 'k':
    case 'ArrowUp':
      return { kind: 'move', by: -1 };
    case 'u':
      return { kind: 'undo' };
    case 'n':
      return { kind: 'next' };
    case 'e':
      return { kind: 'evaluate' };
    case '?':
      return { kind: 'keys' };
    default:
      return null;
  }
}

/** The option a listbox key moves to, clamped to the list, or `null` for other keys. */
export function optionAfter(
  index: number,
  key: string,
  count: number,
): number | null {
  const last = count - 1;
  switch (key) {
    case 'ArrowDown':
      return Math.min(index + 1, last);
    case 'ArrowUp':
      return Math.max(index - 1, 0);
    case 'Home':
      return 0;
    case 'End':
      return last;
    default:
      return null;
  }
}
