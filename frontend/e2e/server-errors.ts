import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

export default function checkServerErrors(): void {
  const directory = process.env.ROWSETTA_E2E_SESSIONS;
  if (directory === undefined)
    throw new Error('Missing E2E server log directory.');
  for (const file of readdirSync(directory).filter((name) =>
    name.endsWith('.errors.log'),
  )) {
    const errors = readFileSync(join(directory, file), 'utf8').trim();
    if (errors !== '')
      throw new Error(`Unhandled server errors in ${file}:\n${errors}`);
  }
}
