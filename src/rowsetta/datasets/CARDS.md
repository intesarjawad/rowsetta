# Bundled dataset cards

Sources and licences checked on 2026-11-05. Rebuild with
`uv run --locked python scripts/fetch_datasets.py`. Downloads are verified before
processing; no user data is sent. CSV files live beside this document.

## Palmer penguins

Files: `penguins.csv` (344 rows, target `species`).

Licence: CC0.

Citation: Horst, A. M., Hill, A. P., and Gorman, K. B. (2020).
_palmerpenguins: Palmer Archipelago (Antarctica) penguin data_.
[Package citation and licence](https://allisonhorst.github.io/palmerpenguins/).
[DOI](https://doi.org/10.5281/zenodo.3960218).
Original research: Gorman, K. B., Williams, T. D., and Fraser, W. R. (2014).
_Ecological sexual dimorphism and environmental variability within a community
of Antarctic penguins (genus Pygoscelis)_.
[DOI](https://doi.org/10.1371/journal.pone.0090081).

[Source CSV](https://raw.githubusercontent.com/allisonhorst/palmerpenguins/main/inst/extdata/penguins.csv)
SHA-256: `f204db2c753b0937caac3cb35258562c14f073e4bbc76be24b4c51ce22767a93`.
Copied byte for byte, retaining the source's `NA` markers.

## Bank Marketing

Files: `bank.csv` (5,000 rows), `bank_2k.csv` (2,000 rows), target `y`.

Licence: CC BY 4.0.

Citation: Moro, S., Rita, P., and Cortez, P. (2014). _Bank Marketing_ [Dataset].
UCI Machine Learning Repository.
[Dataset and licence](https://archive.ics.uci.edu/dataset/222/bank+marketing).
[DOI](https://doi.org/10.24432/C5K306).

[Source archive](https://archive.ics.uci.edu/static/public/222/bank+marketing.zip)
SHA-256: `e0bf5f5de5b846e2f18e9d90606637267d46dfa260e0f17bb12e605db5efbeb4`.
Read the nested `bank.zip`'s semicolon-separated `bank-full.csv` (45,211 rows).
Stratify 5,000 rows on `y` with seed 7, then stratify 2,000 from those 5,000
with seed 7. Write comma-separated UTF-8 CSV without an index.

`duration` is call length in seconds, available only after the call. Retained to
demonstrate a post-outcome feature that must be excluded for pre-call prediction.
It is only moderately predictive. The near-perfect leak check does not flag it;
the later golden leak fixture uses an injected near-copy of `y` instead.

## Adult

Files: `adult.csv` (5,000 rows), `adult_2k.csv` (2,000 rows), target `income`.

Licence: CC BY 4.0.

Citation: Becker, B., and Kohavi, R. (1996). _Adult_ [Dataset].
UCI Machine Learning Repository.
[Dataset and licence](https://archive.ics.uci.edu/dataset/2/adult).
[DOI](https://doi.org/10.24432/C5XW20).

[Source archive](https://archive.ics.uci.edu/static/public/2/adult.zip)
SHA-256: `7537312dd56c2b98035880805ce99e68183a30ee468aa5329d6df0fbb3cc21bb`.
Use only `adult.data` (32,561 rows), not `adult.test`. Read attribute names in
order from `adult.names`, append `income`, trim spaces after separators, and map
`?` to empty cells. Stratify 5,000 rows on `income` with seed 7, then 2,000 from
that file with seed 7. Write comma-separated UTF-8 CSV without an index.

## Sampling and redistribution

The two sampled sources allocate class counts by largest remainder, breaking
ties by sorted class label, then use pandas sampling with seed 7 within each
class and restore source order. Browser files are subsets of their local files.
Tests enforce class-share differences of at most 0.5 percentage points.
These samples and the Adult missing-value normalization are modifications of the
credited sources. Retain this attribution when redistributing them under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
