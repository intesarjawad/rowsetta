# Dataset card index

The bundled CSV files and full source citations, checksums, processing notes and
licences are in [the packaged cards](../src/rowsetta/datasets/CARDS.md).

| Dataset         | Files                       | Licence   |
| --------------- | --------------------------- | --------- |
| Palmer penguins | `penguins.csv`              | CC0       |
| Bank Marketing  | `bank.csv`, `bank_2k.csv`   | CC BY 4.0 |
| Adult           | `adult.csv`, `adult_2k.csv` | CC BY 4.0 |
| Dry Bean        | `dry_bean.zip`             | CC BY 4.0 |
| Mushroom        | `mushroom.zip`             | CC BY 4.0 |
| Car Evaluation  | `car.zip`                  | CC BY 4.0 |

The three ZIP archives are benchmark-only and are not bundled. Fetch and verify
them with `uv run python scripts/fetch_bench_datasets.py --verify`. Unmodified
source archives are cached under `~/.cache/rowsetta/bench/`, or beneath
`XDG_CACHE_HOME` when set. Checksums are pinned in that script and recorded in
[ADR 0009](../docs/adr/0009-third-party-browser-pieces.md#benchmark-source-verification).

Each source page explicitly states CC BY 4.0, verified on 2026-11-05:

- Dry Bean [Dataset]. (2020). UCI Machine Learning Repository.
  <https://doi.org/10.24432/C50S4B>.
  [Source and licence](https://archive.ics.uci.edu/dataset/602/dry+bean+dataset).
- Mushroom [Dataset]. (1981). UCI Machine Learning Repository.
  <https://doi.org/10.24432/C5959T>.
  [Source and licence](https://archive.ics.uci.edu/dataset/73/mushroom).
- Bohanec, M. (1988). Car Evaluation [Dataset]. UCI Machine Learning Repository.
  <https://doi.org/10.24432/C5JP48>.
  [Source and licence](https://archive.ics.uci.edu/dataset/19/car+evaluation).
