import type { ExportArtifact } from './backend/types';

// SQL and the dbt model comment the certificate with `-- `, Python with `# `.
const HEADER_LINE = /^(?:-- |# )/;

/**
 * The certificate an export opens with: measured figures and provenance, without
 * the per-column type lines. JSON states it as data instead, so it gives none.
 */
export function certificateFigures(artifact: ExportArtifact): string[] {
  const text =
    artifact.format === 'dbt'
      ? (Object.entries(artifact.files).find(
          ([path]) => path.startsWith('models/') && path.endsWith('.sql'),
        )?.[1] ?? '')
      : artifact.text;
  const figures: string[] = [];
  for (const line of text.split('\n')) {
    const prefix = HEADER_LINE.exec(line);
    if (prefix === null) break;
    const figure = line.slice(prefix[0].length);
    if (!figure.startsWith('Column ')) figures.push(figure);
  }
  return figures;
}
