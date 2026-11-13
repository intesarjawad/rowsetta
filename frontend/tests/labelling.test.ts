import { describe, expect, it } from 'vitest';
import type { WorkspaceState } from '../src/backend/types';
import {
  NO_PROPOSALS,
  missingText,
  nextProposals,
  optionAfter,
  rowLabel,
  rowLabelText,
  tableCommand,
  type KeyPress,
  type ShownProposals,
} from '../src/labelling';

const BASE: WorkspaceState = {
  loaded: true,
  notice: null,
  target: 'species',
  classes: ['Adelie', 'Chinstrap', 'Gentoo'],
  human: {},
  eval_count: 0,
  threshold: 0.6,
  excluded_columns: [],
  generation: 6,
  refit_generation: 6,
  proposals: { '7': 'Gentoo', '8': 'Adelie' },
  confidence: { '7': 0.9, '8': 0.4 },
  abstained: [8],
  missing: {},
  next_row: 7,
  evaluation: null,
  failure: null,
  dev_states: false,
};

const FITTED: ShownProposals = {
  target: 'species',
  labels: BASE.proposals,
  unsure: new Set([8]),
  stale: false,
};

function press(key: string, modifiers: Partial<KeyPress> = {}): KeyPress {
  return {
    key,
    altKey: false,
    ctrlKey: false,
    metaKey: false,
    ...modifiers,
  };
}

describe('shown proposals', () => {
  it('takes the proposals of a state fitted on its current inputs', () => {
    expect(nextProposals(NO_PROPOSALS, BASE)).toEqual(FITTED);
  });

  it('keeps the last proposals, marked stale, while a refit is pending', () => {
    const editing = {
      ...BASE,
      generation: 7,
      proposals: {},
      confidence: {},
      abstained: [],
    };

    expect(nextProposals(FITTED, editing)).toEqual({ ...FITTED, stale: true });
  });

  it('drops them when the target changes, since they answer another question', () => {
    const retargeted = {
      ...BASE,
      target: 'island',
      generation: 7,
      proposals: {},
    };

    expect(nextProposals(FITTED, retargeted)).toEqual({
      ...NO_PROPOSALS,
      target: 'island',
    });
  });

  it('drops them once an undo leaves a class below the label minimum', () => {
    const undone = {
      ...BASE,
      generation: 7,
      proposals: {},
      missing: { Gentoo: 1 },
    };

    expect(nextProposals(FITTED, undone)).toEqual({
      ...NO_PROPOSALS,
      target: 'species',
    });
  });
});

describe('row label states', () => {
  const human = { '3': 'Chinstrap', '7': 'Adelie' };

  it('prefers a human label over a proposal for the same row', () => {
    expect(rowLabel(7, human, FITTED)).toEqual({
      kind: 'human',
      label: 'Adelie',
    });
  });

  it('shows an abstaining row as unsure, not with its weak label', () => {
    expect(rowLabel(8, {}, FITTED)).toEqual({ kind: 'unsure', stale: false });
  });

  it('shows a proposal and whether it is stale', () => {
    expect(rowLabel(7, {}, { ...FITTED, stale: true })).toEqual({
      kind: 'proposed',
      label: 'Gentoo',
      stale: true,
    });
  });

  it('shows a row with neither as unlabelled', () => {
    expect(rowLabel(99, human, FITTED)).toEqual({ kind: 'unlabelled' });
  });

  it('names every state in words', () => {
    expect(rowLabelText({ kind: 'human', label: 'Adelie' })).toBe(
      'Labelled Adelie',
    );
    expect(
      rowLabelText({ kind: 'proposed', label: 'Gentoo', stale: false }),
    ).toBe('Proposed Gentoo');
    expect(
      rowLabelText({ kind: 'proposed', label: 'Gentoo', stale: true }),
    ).toBe('Proposed Gentoo, updating');
    expect(rowLabelText({ kind: 'unsure', stale: false })).toBe('Unsure');
    expect(rowLabelText({ kind: 'unsure', stale: true })).toBe(
      'Unsure, updating',
    );
    expect(rowLabelText({ kind: 'unlabelled' })).toBe('Unlabelled');
  });
});

describe('labels still needed', () => {
  it('lists each class with its count', () => {
    expect(missingText({ Chinstrap: 1, Gentoo: 2 })).toBe(
      'Proposals start after 1 more Chinstrap, 2 more Gentoo.',
    );
  });

  it('is empty once every class has enough', () => {
    expect(missingText({})).toBe('');
  });
});

describe('table keys', () => {
  it('maps 1 to 9 to the first nine classes', () => {
    expect(tableCommand(press('1'))).toEqual({ kind: 'label', classIndex: 0 });
    expect(tableCommand(press('9'))).toEqual({ kind: 'label', classIndex: 8 });
  });

  it('maps 0 to the tenth class', () => {
    expect(tableCommand(press('0'))).toEqual({ kind: 'label', classIndex: 9 });
  });

  it('moves with j and k or the arrow keys', () => {
    expect(tableCommand(press('j'))).toEqual({ kind: 'move', by: 1 });
    expect(tableCommand(press('ArrowDown'))).toEqual({ kind: 'move', by: 1 });
    expect(tableCommand(press('k'))).toEqual({ kind: 'move', by: -1 });
    expect(tableCommand(press('ArrowUp'))).toEqual({ kind: 'move', by: -1 });
  });

  it('undoes with u', () => {
    expect(tableCommand(press('u'))).toEqual({ kind: 'undo' });
  });

  it('jumps to the next suggested row with n, evaluates with e and lists keys with ?', () => {
    expect(tableCommand(press('n'))).toEqual({ kind: 'next' });
    expect(tableCommand(press('e'))).toEqual({ kind: 'evaluate' });
    expect(tableCommand(press('?'))).toEqual({ kind: 'keys' });
  });

  it('leaves browser and system shortcuts alone', () => {
    expect(tableCommand(press('u', { ctrlKey: true }))).toBeNull();
    expect(tableCommand(press('1', { metaKey: true }))).toBeNull();
    expect(tableCommand(press('j', { altKey: true }))).toBeNull();
  });

  it('ignores keys without a shortcut, including capitals', () => {
    expect(tableCommand(press('Tab'))).toBeNull();
    expect(tableCommand(press('Enter'))).toBeNull();
    expect(tableCommand(press('U'))).toBeNull();
    expect(tableCommand(press('E'))).toBeNull();
  });
});

describe('listbox keys', () => {
  it('moves one option at a time without wrapping', () => {
    expect(optionAfter(0, 'ArrowDown', 3)).toBe(1);
    expect(optionAfter(2, 'ArrowDown', 3)).toBe(2);
    expect(optionAfter(1, 'ArrowUp', 3)).toBe(0);
    expect(optionAfter(0, 'ArrowUp', 3)).toBe(0);
  });

  it('jumps to the first and last option', () => {
    expect(optionAfter(1, 'Home', 3)).toBe(0);
    expect(optionAfter(0, 'End', 3)).toBe(2);
  });

  it('ignores other keys', () => {
    expect(optionAfter(1, 'Tab', 3)).toBeNull();
  });
});
