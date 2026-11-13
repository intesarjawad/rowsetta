import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { BackendError, createBackend } from '../src/backend/http';
import {
  COLUMN_KINDS,
  EXPORT_FORMATS,
  LABEL_MODES,
  LEAK_KINDS,
  SQL_DIALECTS,
  type ColumnInfo,
  type Distilled,
  type DistillInput,
  type ErrorBody,
  type Evaluation,
  type ExclusionInput,
  type LabelInput,
  type LeafLine,
  type LeakHint,
  type Measured,
  type NeedsRows,
  type Suspect,
  type TablePage,
  type TargetInput,
  type ThresholdInput,
  type WorkspaceState,
} from '../src/backend/types';

// Regenerate with: uv run python scripts/export_openapi.py > frontend/tests/openapi.json
const openapi: unknown = JSON.parse(
  readFileSync(new URL('openapi.json', import.meta.url), 'utf8'),
);

type Json = Record<string, unknown>;

function isJson(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function at(value: unknown, ...keys: string[]): Json {
  let current = value;
  for (const key of keys) {
    if (!isJson(current)) {
      throw new Error(`openapi.json: no object at ${keys.join('.')}`);
    }
    current = current[key];
  }
  if (!isJson(current)) {
    throw new Error(`openapi.json: no object at ${keys.join('.')}`);
  }
  return current;
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : [];
}

// The wire type a TypeScript field must have. TypeScript cannot tell integers
// from floats, so the test pins which one each number field is. Nested models
// are `object` here and checked under their own schema name.
type WireType<V> = [V] extends [string]
  ? 'string'
  : [V] extends [number]
    ? 'number' | 'integer'
    : [V] extends [boolean]
      ? 'boolean'
      : [V] extends [string | number | boolean]
        ? [string | number | boolean] extends [V]
          ? 'boolean|integer|number|string'
          : never
        : [V] extends [readonly (infer Item)[]]
          ? `array<${WireType<Item>}>`
          : [V] extends [object]
            ? string extends keyof V
              ? `record<${WireType<NonNullable<V[string]>>}${null extends V[string] ? '|null' : ''}>`
              : 'object'
            : never;

type FieldShapes<T> = {
  [K in keyof T]-?: {
    type: WireType<NonNullable<T[K]>>;
    nullable: null extends T[K] ? true : false;
    required: Pick<T, K> extends Required<Pick<T, K>> ? true : false;
  };
};

const requestBodies = {
  DistillInput: {
    max_depth: { type: 'integer', nullable: false, required: false },
  } satisfies FieldShapes<DistillInput>,
  ExclusionInput: {
    excluded: { type: 'boolean', nullable: false, required: true },
  } satisfies FieldShapes<ExclusionInput>,
  LabelInput: {
    label: { type: 'string', nullable: true, required: true },
    mode: { type: 'string', nullable: false, required: false },
  } satisfies FieldShapes<LabelInput>,
  TargetInput: {
    target: { type: 'string', nullable: false, required: true },
    classes: { type: 'array<string>', nullable: false, required: false },
  } satisfies FieldShapes<TargetInput>,
  ThresholdInput: {
    threshold: { type: 'number', nullable: false, required: true },
  } satisfies FieldShapes<ThresholdInput>,
};

// Envelopes the client unwraps before returning their single field.
interface Audit {
  leaks: readonly LeakHint[];
}
interface EvalNext {
  row_id: number | null;
}
interface Health {
  ok: boolean;
}

const responseBodies = {
  Agreement: {
    k: { type: 'integer', nullable: false, required: true },
    n: { type: 'integer', nullable: false, required: true },
    coverage: { type: 'object', nullable: false, required: true },
  } satisfies FieldShapes<LeafLine['agree']>,
  Audit: {
    leaks: { type: 'array<object>', nullable: false, required: true },
  } satisfies FieldShapes<Audit>,
  ColumnInfo: {
    name: { type: 'string', nullable: false, required: true },
    kind: { type: 'string', nullable: false, required: true },
    distinct_ratio: { type: 'number', nullable: false, required: true },
    missing_ratio: { type: 'number', nullable: false, required: true },
  } satisfies FieldShapes<ColumnInfo>,
  Coverage: {
    answered: { type: 'integer', nullable: false, required: true },
    total: { type: 'integer', nullable: false, required: true },
  } satisfies FieldShapes<LeafLine['agree']['coverage']>,
  Distilled: {
    leaf_summary: { type: 'array<object>', nullable: false, required: true },
    disagreements: {
      type: 'array<integer>',
      nullable: false,
      required: true,
    },
    generation: { type: 'integer', nullable: false, required: true },
  } satisfies FieldShapes<Distilled>,
  ErrorBody: {
    error: { type: 'string', nullable: false, required: true },
    next_step: { type: 'string', nullable: false, required: true },
    missing: { type: 'record<integer>', nullable: false, required: false },
  } satisfies FieldShapes<ErrorBody>,
  EvalNext: {
    row_id: { type: 'integer', nullable: true, required: true },
  } satisfies FieldShapes<EvalNext>,
  Evaluation: {
    n: { type: 'integer', nullable: false, required: true },
    accuracy: { type: 'object', nullable: false, required: true },
    balanced_accuracy: { type: 'object', nullable: false, required: true },
    per_class_recall: {
      type: 'record<number|null>',
      nullable: false,
      required: true,
    },
    majority_class: { type: 'string', nullable: false, required: true },
    majority_baseline: { type: 'number', nullable: false, required: true },
  } satisfies FieldShapes<Evaluation>,
  Health: {
    ok: { type: 'boolean', nullable: false, required: true },
  } satisfies FieldShapes<Health>,
  LeafLine: {
    line_no: { type: 'integer', nullable: false, required: true },
    conditions: {
      type: 'array<array<string>>',
      nullable: false,
      required: true,
    },
    label: { type: 'string', nullable: true, required: true },
    row_ids: { type: 'array<integer>', nullable: false, required: true },
    agree: { type: 'object', nullable: false, required: true },
  } satisfies FieldShapes<LeafLine>,
  LeakHint: {
    column: { type: 'string', nullable: false, required: true },
    kind: { type: 'string', nullable: false, required: true },
    reason: { type: 'string', nullable: false, required: true },
    score: { type: 'number', nullable: true, required: true },
  } satisfies FieldShapes<LeakHint>,
  Suspect: {
    row_id: { type: 'integer', nullable: false, required: true },
    given: { type: 'string', nullable: false, required: true },
    given_probability: { type: 'number', nullable: false, required: true },
    likely: { type: 'string', nullable: false, required: true },
  } satisfies FieldShapes<Suspect>,
  Suspects: {
    suspects: { type: 'array<object>', nullable: false, required: true },
  } satisfies FieldShapes<{ suspects: readonly Suspect[] }>,
  Measured: {
    kind: { type: 'string', nullable: false, required: true },
    value: { type: 'number', nullable: false, required: true },
    lo: { type: 'number', nullable: false, required: true },
    hi: { type: 'number', nullable: false, required: true },
  } satisfies FieldShapes<Measured>,
  NeedsRows: {
    kind: { type: 'string', nullable: false, required: true },
    counts: { type: 'record<integer>', nullable: false, required: true },
  } satisfies FieldShapes<NeedsRows>,
  TablePage: {
    rows: {
      type: 'array<record<boolean|integer|number|string|null>>',
      nullable: false,
      required: true,
    },
    row_ids: { type: 'array<integer>', nullable: false, required: true },
    columns: { type: 'array<object>', nullable: false, required: true },
    total: { type: 'integer', nullable: false, required: true },
    source_rows: { type: 'integer', nullable: false, required: true },
    page: { type: 'integer', nullable: false, required: true },
    size: { type: 'integer', nullable: false, required: true },
  } satisfies FieldShapes<TablePage>,
  WorkspaceState: {
    loaded: { type: 'boolean', nullable: false, required: true },
    file_name: { type: 'string', nullable: true, required: false },
    notice: { type: 'string', nullable: true, required: true },
    target: { type: 'string', nullable: true, required: true },
    classes: { type: 'array<string>', nullable: false, required: true },
    human: { type: 'record<string>', nullable: false, required: true },
    eval_count: { type: 'integer', nullable: false, required: true },
    threshold: { type: 'number', nullable: false, required: true },
    excluded_columns: {
      type: 'array<string>',
      nullable: false,
      required: true,
    },
    generation: { type: 'integer', nullable: false, required: true },
    refit_generation: { type: 'integer', nullable: true, required: true },
    proposals: { type: 'record<string>', nullable: false, required: true },
    confidence: { type: 'record<number>', nullable: false, required: true },
    abstained: { type: 'array<integer>', nullable: false, required: true },
    missing: { type: 'record<integer>', nullable: false, required: true },
    next_row: { type: 'integer', nullable: true, required: true },
    evaluation: { type: 'object', nullable: true, required: true },
    failure: { type: 'object', nullable: true, required: true },
    dev_states: { type: 'boolean', nullable: false, required: true },
  } satisfies FieldShapes<WorkspaceState>,
};

// The model each client call decodes. Routes absent here answer with a file,
// a stream or the page itself rather than a JSON model.
const responseSchemas: Readonly<Record<string, string>> = {
  'GET /audit': 'Audit',
  'GET /eval/next': 'EvalNext',
  'GET /health': 'Health',
  'GET /state': 'WorkspaceState',
  'GET /suspects': 'Suspects',
  'GET /table': 'TablePage',
  'POST /distill': 'Distilled',
  'POST /table': 'WorkspaceState',
  'POST /target': 'WorkspaceState',
  'POST /undo': 'WorkspaceState',
  'PUT /columns/{name}/excluded': 'WorkspaceState',
  'PUT /labels/{row_id}': 'WorkspaceState',
  'PUT /threshold': 'WorkspaceState',
};

function variantsOf(property: Json): Json[] | undefined {
  const variants = property['anyOf'] ?? property['oneOf'];
  return Array.isArray(variants) ? variants.filter(isJson) : undefined;
}

function isNull(property: Json): boolean {
  return property['type'] === 'null';
}

function referenced(property: Json): Json {
  const reference = property['$ref'];
  const name =
    typeof reference === 'string' ? reference.split('/').at(-1) : undefined;
  return at(openapi, 'components', 'schemas', name ?? '');
}

// Union members are sorted and `null` goes last, matching `WireType`.
// A reference to a model is `object`; a reference to an alias is its type.
function wireType(property: Json): string {
  if ('$ref' in property) {
    const schema = referenced(property);
    return 'properties' in schema ? 'object' : wireType(schema);
  }
  const variants = variantsOf(property);
  if (variants !== undefined) {
    const present = [
      ...new Set(variants.filter((v) => !isNull(v)).map(wireType)),
    ];
    const union = present.every((type) => type === 'object')
      ? 'object'
      : present.sort().join('|');
    return variants.some(isNull) ? `${union}|null` : union;
  }
  const type = property['type'];
  if (type === 'array') {
    if (Array.isArray(property['prefixItems'])) {
      const items = new Set(
        property['prefixItems'].filter(isJson).map(wireType),
      );
      if (items.size !== 1) {
        throw new Error(
          `openapi.json: mixed tuple ${JSON.stringify(property)}`,
        );
      }
      return `array<${[...items].join('')}>`;
    }
    return `array<${wireType(at(property, 'items'))}>`;
  }
  if (type === 'object' && isJson(property['additionalProperties'])) {
    return `record<${wireType(property['additionalProperties'])}>`;
  }
  if (typeof type !== 'string' || type === 'object') {
    throw new Error(
      `openapi.json: untyped property ${JSON.stringify(property)}`,
    );
  }
  return type;
}

function fieldShape(property: Json, required: boolean) {
  const variants = variantsOf(property) ?? [property];
  const present = variants.filter((variant) => !isNull(variant));
  const [only] = present;
  if (only === undefined) {
    throw new Error(
      `openapi.json: ambiguous property ${JSON.stringify(property)}`,
    );
  }
  return {
    type: present.length === 1 ? wireType(only) : wireType({ anyOf: present }),
    nullable: present.length !== variants.length,
    required,
  };
}

function servedFields(schemaName: string) {
  const schema = at(openapi, 'components', 'schemas', schemaName);
  const required = strings(schema['required']);
  return Object.fromEntries(
    Object.entries(at(schema, 'properties')).map(([name, property]) => {
      if (!isJson(property)) {
        throw new Error(`openapi.json: ${schemaName}.${name} is not a schema`);
      }
      return [name, fieldShape(property, required.includes(name))];
    }),
  );
}

describe('request bodies match the served OpenAPI schema', () => {
  it.each(Object.entries(requestBodies))(
    '%s has the same field names, types, nullability and optionality',
    (schemaName, fields) => {
      expect(servedFields(schemaName)).toEqual(fields);
    },
  );

  it('declares a type for every input model the backend validates', () => {
    const served = Object.keys(at(openapi, 'components', 'schemas')).filter(
      (name) => name.endsWith('Input'),
    );

    expect(served.sort()).toEqual(Object.keys(requestBodies).sort());
  });

  it('uses the served label modes, export formats and SQL dialects', () => {
    const exportParameters = at(openapi, 'paths', '/export', 'get')[
      'parameters'
    ];
    const dialect = Array.isArray(exportParameters)
      ? exportParameters.filter(isJson).find((p) => p['name'] === 'dialect')
      : undefined;

    expect(
      strings(
        at(
          openapi,
          'components',
          'schemas',
          'LabelInput',
          'properties',
          'mode',
        )['enum'],
      ),
    ).toEqual(LABEL_MODES);
    expect(
      strings(at(openapi, 'components', 'schemas', 'ExportFormat')['enum']),
    ).toEqual(EXPORT_FORMATS);
    expect(strings(at(dialect, 'schema')['enum'])).toEqual(SQL_DIALECTS);
  });
});

function responseSchemaName(operation: Json): string | undefined {
  const content = at(operation, 'responses', '200', 'content');
  const schema = isJson(content['application/json'])
    ? at(content['application/json'], 'schema')
    : {};
  const reference = schema['$ref'];
  return typeof reference === 'string'
    ? reference.split('/').at(-1)
    : undefined;
}

describe('response bodies match the served OpenAPI schema', () => {
  it.each(Object.entries(responseBodies))(
    '%s has the same field names, types, nullability and optionality',
    (schemaName, fields) => {
      expect(servedFields(schemaName)).toEqual(fields);
    },
  );

  it('declares a type for every model the backend serves, and no other', () => {
    // FastAPI adds the validation error models; this backend never sends them.
    const frameworkModels = ['HTTPValidationError', 'ValidationError'];
    const served = Object.entries(at(openapi, 'components', 'schemas'))
      .filter(
        ([name, schema]) =>
          isJson(schema) &&
          'properties' in schema &&
          !name.endsWith('Input') &&
          !frameworkModels.includes(name),
      )
      .map(([name]) => name);

    expect(served.sort()).toEqual(Object.keys(responseBodies).sort());
  });

  it('answers each JSON route with the model its client call decodes', () => {
    const served = Object.entries(at(openapi, 'paths')).flatMap(
      ([path, operations]) =>
        Object.entries(at(operations)).flatMap(([method, operation]) => {
          const name = responseSchemaName(at(operation));
          return name === undefined
            ? []
            : [[`${method.toUpperCase()} ${path}`, name] as const];
        }),
    );

    expect(Object.fromEntries(served)).toEqual(responseSchemas);
  });

  it('tags the measurement union by kind and uses the served enums', () => {
    const schemas = at(openapi, 'components', 'schemas');
    const balanced = at(
      schemas,
      'Evaluation',
      'properties',
      'balanced_accuracy',
    );

    expect(at(balanced, 'discriminator')['propertyName']).toBe('kind');
    expect(at(schemas, 'Measured', 'properties', 'kind')['const']).toBe(
      'measured',
    );
    expect(at(schemas, 'NeedsRows', 'properties', 'kind')['const']).toBe(
      'needs_rows',
    );
    expect(
      strings(at(schemas, 'ColumnInfo', 'properties', 'kind')['enum']),
    ).toEqual(COLUMN_KINDS);
    expect(
      strings(at(schemas, 'LeakHint', 'properties', 'kind')['enum']),
    ).toEqual(LEAK_KINDS);
  });
});

interface RecordedRequest {
  method: string;
  url: URL;
  body: BodyInit | null | undefined;
}

// The page itself is the one route the browser reaches without this client.
const OUTSIDE_CLIENT = ['GET /'];

function operationKey(request: RecordedRequest): string {
  const templates = Object.keys(at(openapi, 'paths'));
  const template = templates.find((path) =>
    new RegExp(`^${path.replace(/\{[^/]+\}/g, '[^/]+')}$`).test(
      request.url.pathname,
    ),
  );
  if (template === undefined) {
    throw new Error(`no served path matches ${request.url.pathname}`);
  }
  return `${request.method} ${template}`;
}

async function recordEveryRequest(): Promise<RecordedRequest[]> {
  const requests: RecordedRequest[] = [];
  const backend = createBackend(
    (input, init) => {
      requests.push({
        method: init.method ?? 'GET',
        url: new URL(input, 'http://127.0.0.1'),
        body: init.body,
      });
      return Promise.resolve(
        Response.json({ error: 'stub', next_step: 'stub' }, { status: 409 }),
      );
    },
    (url) => {
      requests.push({
        method: 'GET',
        url: new URL(url, 'http://127.0.0.1'),
        body: undefined,
      });
      return { addEventListener: () => undefined, close: () => undefined };
    },
  );
  backend.events(() => undefined)();
  const calls = [
    () => backend.health(),
    () => backend.session(),
    () => backend.state(),
    () => backend.loadDemo(),
    () => backend.uploadCsv(new File(['a,b\n1,2\n'], 'rows.csv')),
    () => backend.tablePage({ page: 2, size: 100 }),
    () =>
      backend.setTarget({ target: 'species', classes: ['Adelie', 'Gentoo'] }),
    () => backend.setLabel(7, { label: 'Adelie', mode: 'eval' }),
    () => backend.undo(),
    () => backend.nextEvalRow(),
    () => backend.setExcluded('bill length', { excluded: true }),
    () => backend.setThreshold({ threshold: 0.8 }),
    () => backend.distill({ max_depth: 3 }),
    () => backend.audit(),
    () => backend.suspects(),
    () => backend.exportRule({ format: 'sql', dialect: 'postgres' }),
  ];
  for (const call of calls) {
    await expect(call()).rejects.toBeInstanceOf(BackendError);
  }
  return requests;
}

describe('client requests match served operations', () => {
  it('covers every served operation outside the documented exceptions', async () => {
    const used = new Set((await recordEveryRequest()).map(operationKey));
    const served = Object.entries(at(openapi, 'paths')).flatMap(
      ([path, operations]) =>
        Object.keys(at(operations)).map(
          (method) => `${method.toUpperCase()} ${path}`,
        ),
    );

    expect(served.filter((key) => !used.has(key)).sort()).toEqual(
      OUTSIDE_CLIENT,
    );
  });

  it('sends only declared query parameters and well-typed path parameters', async () => {
    for (const request of await recordEveryRequest()) {
      const [method = '', path = ''] = operationKey(request).split(' ');
      const declared = at(openapi, 'paths', path, method.toLowerCase())[
        'parameters'
      ];
      const parameters = Array.isArray(declared) ? declared.filter(isJson) : [];
      const queryNames = parameters
        .filter((p) => p['in'] === 'query')
        .map((p) => p['name']);

      expect(queryNames).toEqual(
        expect.arrayContaining([...request.url.searchParams.keys()]),
      );
      for (const parameter of parameters.filter((p) => p['in'] === 'path')) {
        const name = parameter['name'];
        if (
          typeof name === 'string' &&
          at(parameter, 'schema')['type'] === 'integer'
        ) {
          const index = path.split('/').indexOf(`{${name}}`);
          expect(request.url.pathname.split('/')[index]).toMatch(/^\d+$/);
        }
      }
    }
  });

  it('sends JSON bodies with exactly the fields their input model accepts', async () => {
    for (const request of await recordEveryRequest()) {
      if (typeof request.body !== 'string') {
        continue;
      }
      const key = operationKey(request);
      const [method = '', path = ''] = key.split(' ');
      const operation = at(openapi, 'paths', path, method.toLowerCase());
      if (!('requestBody' in operation)) {
        // The upload route reads its raw body to bound its size, then validates DemoInput itself.
        expect(key).toBe('POST /table');
        expect(JSON.parse(request.body)).toEqual({ demo: 'penguins' });
        continue;
      }
      const reference = at(
        operation,
        'requestBody',
        'content',
        'application/json',
        'schema',
      )['$ref'];
      const schemaName =
        typeof reference === 'string' ? reference.split('/').at(-1) : undefined;
      const schema = at(openapi, 'components', 'schemas', schemaName ?? '');
      const sent = Object.keys(at(JSON.parse(request.body)));

      expect(Object.keys(at(schema, 'properties'))).toEqual(
        expect.arrayContaining(sent),
      );
      expect(sent).toEqual(expect.arrayContaining(strings(schema['required'])));
    }
  });
});
