import type { LeafLine } from './backend/types';
import type { Point } from './transit';
export interface Drawn {
  key: string;
  points: Point[];
  width: number;
  colour: string;
  casing: boolean;
  row: number | null;
  rows: number;
  opacity: number;
}
export interface Ghost {
  key: string;
  label: string | null;
  rows: number;
  into: LeafLine;
  toY: number;
  order: number;
}
