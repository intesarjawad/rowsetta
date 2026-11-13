import type { Cell } from 'forecast-web/tabular';
import type { loadTeacher } from './teacher';

function cells(value: unknown): Cell[][] {
  if (!Array.isArray(value)) throw new Error('Invalid refit rows');
  return value.map((row: unknown) => {
    if (!Array.isArray(row)) throw new Error('Invalid refit row');
    return row.map((cell: unknown) => {
      if (
        cell === null ||
        typeof cell === 'string' ||
        typeof cell === 'boolean' ||
        (typeof cell === 'number' && Number.isFinite(cell))
      )
        return cell;
      throw new Error('Invalid refit cell');
    });
  });
}

/** Only serialized feature tables cross the Python/JavaScript boundary inside this worker. */
export async function predictRefit(
  model: Awaited<ReturnType<typeof loadTeacher>>,
  input: string,
): Promise<string | null> {
  const data: unknown = JSON.parse(input);
  if (data === null) return null;
  if (
    typeof data !== 'object' ||
    !('generation' in data) ||
    typeof data.generation !== 'number' ||
    !('train' in data) ||
    !('test' in data) ||
    !('labels' in data) ||
    !Array.isArray(data.labels)
  )
    throw new Error('Invalid refit input');
  const labels = data.labels.map((label: unknown) => {
    if (typeof label !== 'string') throw new Error('Invalid refit label');
    return label;
  });
  const fitted = model.fit(cells(data.train), labels);
  const probabilities = await fitted.predictProba(cells(data.test));
  return JSON.stringify({
    generation: data.generation,
    classes: fitted.classes,
    probabilities,
  });
}
