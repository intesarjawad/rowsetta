import type { Backend } from './backend/http';
import type { Cell, ColumnInfo, TablePage } from './backend/types';
import { PAGE_SIZE } from './labelling';
import type { RowFilter } from './rule';

// The largest page the server sends.
const FETCH_SIZE = 1000;

type Row = Readonly<Record<string, Cell>>;

/** Every working row, for filters and jumps to a row on another page. */
export interface WholeTable {
  rowIds: readonly number[];
  rows: ReadonlyMap<number, Row>;
  columns: readonly ColumnInfo[];
  sourceRows: number;
}

export async function fetchWholeTable(backend: Backend): Promise<WholeTable> {
  const first = await backend.tablePage({ page: 0, size: FETCH_SIZE });
  const pageCount = Math.ceil(first.total / FETCH_SIZE);
  const rest = await Promise.all(
    Array.from({ length: Math.max(pageCount - 1, 0) }, (_, index) =>
      backend.tablePage({ page: index + 1, size: FETCH_SIZE }),
    ),
  );
  const pages = [first, ...rest];
  const rowIds = pages.flatMap((page) => page.row_ids);
  const rows = new Map(
    pages.flatMap((page) =>
      page.row_ids.map((rowId, index): [number, Row] => [
        rowId,
        page.rows[index] ?? {},
      ]),
    ),
  );
  return {
    rowIds,
    rows,
    columns: first.columns,
    sourceRows: first.source_rows,
  };
}

/** One page of the filter's rows, shaped like a page the server sends. */
export function filteredPage(
  table: WholeTable,
  filter: RowFilter,
  page: number,
): TablePage {
  const rowIds = filter.rowIds.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  return {
    rows: rowIds.map((rowId) => table.rows.get(rowId) ?? {}),
    row_ids: rowIds,
    columns: table.columns,
    total: filter.rowIds.length,
    source_rows: table.sourceRows,
    page,
    size: PAGE_SIZE,
  };
}
