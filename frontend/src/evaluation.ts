import type { Evaluation, Measured } from './backend/types';

// Mirror src/rowsetta/core/evaluation.py, which withholds each figure below these counts.
export const MIN_EVAL_ROWS = 20;
export const MIN_EVAL_PER_CLASS = 5;

export function percent(rate: number): string {
  return `${String(Math.round(rate * 100))}%`;
}

function interval(measured: Measured): string {
  return `${percent(measured.lo)} to ${percent(measured.hi)}`;
}

/** The accuracy panel's sentences, or how many more evaluation rows they need. */
export function evaluationText(
  evaluation: Evaluation | null,
  evalCount: number,
): string[] {
  if (evaluation === null) {
    return [
      `Label ${String(MIN_EVAL_ROWS)} evaluation rows to see accuracy (${String(evalCount)} so far).`,
    ];
  }
  const { n, accuracy, balanced_accuracy: balanced } = evaluation;
  const balancedText =
    balanced.kind === 'measured'
      ? `Balanced accuracy ${percent(balanced.value)} (${interval(balanced)}).`
      : `Balanced accuracy needs ${String(MIN_EVAL_PER_CLASS)} evaluation rows of each class (${Object.entries(
          balanced.counts,
        )
          .filter(([, count]) => count < MIN_EVAL_PER_CLASS)
          .map(([label, count]) => `${label}: ${String(count)} so far`)
          .join(', ')}).`;
  return [
    `${String(n)} evaluation rows. Accuracy ${percent(accuracy.value)} (95% CI ${interval(accuracy)}).`,
    balancedText,
    `Always guessing ${evaluation.majority_class} would score ${percent(evaluation.majority_baseline)}.`,
  ];
}

export function recallText(label: string, recall: number | null): string {
  return recall === null
    ? `${label}: recall needs ${String(MIN_EVAL_PER_CLASS)} evaluation rows`
    : `${label}: recall ${percent(recall)}`;
}
