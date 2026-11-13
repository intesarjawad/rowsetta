# Bundled data and table loading

## Error names

The errors a user sees when a CSV cannot be opened end in `Error`, so the
names satisfy Ruff N818 without exclusions: `FileTooLargeError`,
`TooManyColumnsError` and `BadCsvError` in `core/errors.py`. There are no
aliases.

Recovery text gives the smallest concrete repair for the failure. Header-only
CSV asks for at least one data row; malformed records ask for correction or
re-export. Encoding failures give a conversion example:
`iconv -f WINDOWS-1252 -t UTF-8 data.csv > data.csv.utf8.csv && rowsetta open data.csv.utf8.csv`.
WINDOWS-1252 is an example; replace it with the actual source encoding.
Conversion writes and opens a separate file, with shell-quoted names. It
cannot repair malformed records. Not every repair starts with an executable.

## Acquisition and provenance

`scripts/fetch_model.py` calls `hf_hub_download` with repository `jingang/TabICL`,
filename `tabicl-classifier-v2-20260212.ckpt` and immutable revision
`4dcd344ece2c00be9e831fdd35bed57b5ad83e19`. The actual download verified:

```text
SHA-256 bdc7dbd5e4ff21f8f0456fcf90c6b7cdf72dbea960f2d05b19bec19f9b3d4ed0
110368038 bytes
```

A hash or size mismatch deletes the downloaded path and exits 1 with
"checkpoint checksum mismatch; delete ~/.cache/huggingface/hub/models--jingang--TabICL
and retry" (`CHECKSUM_ERROR` in `teachers/checkpoint.py`). Verification ran on
macOS without credentials, with
`HF_HOME=/private/tmp/rowsetta-huggingface`; the verified file is under
`hub/models--jingang--TabICL/snapshots/<revision>/` there. The teacher reads the
checkpoint from the same cache, so a different `HF_HOME` needs the fetch script
run again.

`scripts/fetch_datasets.py` checks all three source hashes before writing data.
The destination is `src/rowsetta/datasets/`; the expected hashes are
pinned in that script.
The full [packaged cards](../src/rowsetta/datasets/CARDS.md) hold source
URLs, hashes, citations, licences, modifications and the `duration` leakage note;
[datasets/CARDS.md](../datasets/CARDS.md) indexes them.
Penguins is unchanged, including `NA`. Bank comes from nested `bank.zip` and
`bank-full.csv`, retaining `duration`. Adult uses `adult.data` with headers read
from `adult.names`, spaces after delimiters stripped, and `?` mapped to empty.

Stratification allocates exact class row counts by largest remainder, breaking
ties by sorted class label. Each class is sampled with pandas seed 7 and source
order restored. Each browser sample is drawn from its corresponding local file,
using seed 7 again. Tests verify row counts, subset membership, deterministic
browser sampling, and a maximum 0.5 percentage-point class-share difference.

| File           | Rows  | Columns | Class shares              |
| -------------- | ----- | ------- | ------------------------- |
| `penguins.csv` | 344   | 8       | Source unchanged          |
| `bank.csv`     | 5,000 | 17      | no 88.3%, yes 11.7%       |
| `bank_2k.csv`  | 2,000 | 17      | no 88.3%, yes 11.7%       |
| `adult.csv`    | 5,000 | 15      | <=50K 75.92%, >50K 24.08% |
| `adult_2k.csv` | 2,000 | 15      | <=50K 75.9%, >50K 24.1%   |

The maximum browser/local class-share difference is zero for Bank and 0.02
percentage points for Adult. Both are below the 0.5-point bound the tests assert.

| Bundled file   | SHA-256                                                            |
| -------------- | ------------------------------------------------------------------ |
| `penguins.csv` | `f204db2c753b0937caac3cb35258562c14f073e4bbc76be24b4c51ce22767a93` |
| `bank.csv`     | `298e92bcbc42bd68855b2447bb13fb96b9ca7274b213b80b58691b862f313ed5` |
| `bank_2k.csv`  | `f8831cac119bdad84438d4a14595a132cbd32a4873c9676e02e9dcdaa86bfa2d` |
| `adult.csv`    | `7ed85bcb2a8dcab3c8f73431b5a9d9d61c7dcb81fa534feb911384e252aa61e6` |
| `adult_2k.csv` | `968e35c053f86616c3102248fb1c2e2c1ad8f3a041359dc057738d345948e953` |

## Table loading

- `load_csv` reads bytes only and reports `data.csv`, because it takes no file
  name. Error constructors accept `file_name`, which the CLI passes.
- File limits are checked before decoding. Decimal MB use 1,000,000 bytes;
  recovery budgets round up to a whole MB without rounding the reported size.
- Sampling uses seed 7, preserves original indices and precedes kind inference.
  Distinct and missing ratios use the number of kept rows as their denominator.
  Missing values do not count toward distinct values or datetime parse success.
- Boolean columns, including boolean columns with missing cells, become lowercase
  categorical strings. Numeric columns retain their parsed values. Date inference
  describes the column without converting its values.
- A UTF-8 code point may straddle the 65,536-byte sniff window. An incremental
  decoder permits that boundary without accepting invalid bytes within the window.
- When sniffing the window fails, the loader tries its header and then a comma
  for single-column input. pandas rejects malformed records during parsing.
- pandas can interpret surplus fields in the first data row as an implicit index.
  The loader rejects that case to preserve original zero-based row identities.
- `Table` is frozen but its pandas frame remains mutable. Callers must treat the
  frame as read-only.
- Recovery commands quote file names and column arguments with `shlex.join`.
  `--columns` takes a comma-separated list, so a column name that contains a
  comma cannot be selected with it.

The demo acceptance test checks every column's expected kind for all three local
files. Penguins has five numeric and three categorical columns; Bank has seven
numeric and ten categorical columns; Adult has six numeric and nine categorical
columns. The test includes filesystem reads and asserts each load takes under 1
s.

`uv run --locked python scripts/bench_table.py` measured the real files on this
Mac, including filesystem reads, CSV parsing and inference, with no model load:

```text
penguins.csv: 344 rows, 8 columns, 0.002107 s
bank.csv: 5000 rows, 17 columns, 0.005636 s
adult.csv: 5000 rows, 15 columns, 0.005489 s
bank_2k.csv: 2000 rows, 17 columns, 0.004176 s
adult_2k.csv: 2000 rows, 15 columns, 0.003990 s
```

These are local single-run observations, not a cold-install or portable latency
claim. The table tests also cover separator and BOM handling, seeded 10,001-row
sampling, limits and recovery text, inference thresholds, the 100-column fixture
with long names and Unicode, and the deterministic Hypothesis round trip.
