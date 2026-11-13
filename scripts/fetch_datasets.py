import hashlib
import io
from pathlib import Path
from zipfile import ZipFile

import httpx
import pandas as pd

DESTINATION = Path(__file__).resolve().parents[1] / "src" / "rowsetta" / "datasets"
SAMPLE_SEED = 7
LOCAL_ROWS = 5_000
BROWSER_ROWS = 2_000
PENGUINS_URL = (
    "https://raw.githubusercontent.com/allisonhorst/palmerpenguins/main/inst/extdata/penguins.csv"
)
PENGUINS_SHA256 = "f204db2c753b0937caac3cb35258562c14f073e4bbc76be24b4c51ce22767a93"
BANK_URL = "https://archive.ics.uci.edu/static/public/222/bank+marketing.zip"
BANK_SHA256 = "e0bf5f5de5b846e2f18e9d90606637267d46dfa260e0f17bb12e605db5efbeb4"
ADULT_URL = "https://archive.ics.uci.edu/static/public/2/adult.zip"
ADULT_SHA256 = "7537312dd56c2b98035880805ce99e68183a30ee468aa5329d6df0fbb3cc21bb"


def download_verified(url: str, expected_sha256: str) -> bytes:
    """Reject source drift before parsing or writing bundled data."""
    if not url.startswith("https://"):
        message = "Dataset downloads require HTTPS."
        raise ValueError(message)
    response = httpx.get(url, timeout=120, follow_redirects=True)
    response.raise_for_status()
    data = response.content
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        message = f"dataset checksum mismatch: {url}; expected {expected_sha256}, got {digest}"
        raise SystemExit(message)
    print(f"{url}: {digest}")
    return data


def stratified_sample(frame: pd.DataFrame, target: str, rows: int) -> pd.DataFrame:
    """Allocate whole rows by largest remainder, then sample each class with seed 7."""
    groups = [group for _, group in frame.groupby(target, sort=True)]
    counts = [rows * len(group) // len(frame) for group in groups]
    remainders = [rows * len(group) % len(frame) for group in groups]
    for index in sorted(range(len(groups)), key=lambda index: -remainders[index])[
        : rows - sum(counts)
    ]:
        counts[index] += 1
    return pd.concat(
        [
            group.sample(n=count, random_state=SAMPLE_SEED)
            for group, count in zip(groups, counts, strict=True)
        ]
    ).sort_index()


def write_samples(frame: pd.DataFrame, name: str, target: str) -> None:
    """Derive the browser sample from the local sample, preserving source order."""
    local = stratified_sample(frame, target, LOCAL_ROWS)
    browser = stratified_sample(local, target, BROWSER_ROWS)
    for sample, suffix in ((local, ""), (browser, "_2k")):
        path = DESTINATION / f"{name}{suffix}.csv"
        sample.to_csv(path, index=False, lineterminator="\n")
        print(f"{path.name}: {len(sample)} rows")


def adult_headers(names: str) -> list[str]:
    """Read attribute names from the source dictionary, excluding its comment lines."""
    attributes = [
        line.split(":", maxsplit=1)[0].strip()
        for line in names.splitlines()
        if ":" in line and not line.startswith("|")
    ]
    return [*attributes, "income"]


def main() -> None:
    """Fetch checksum-pinned sources and rebuild the five distributable CSV files."""
    penguins = download_verified(PENGUINS_URL, PENGUINS_SHA256)
    bank_zip = download_verified(BANK_URL, BANK_SHA256)
    adult_zip = download_verified(ADULT_URL, ADULT_SHA256)
    DESTINATION.mkdir(parents=True, exist_ok=True)
    (DESTINATION / "penguins.csv").write_bytes(penguins)
    with (
        ZipFile(io.BytesIO(bank_zip)) as outer,
        ZipFile(io.BytesIO(outer.read("bank.zip"))) as bank,
    ):
        bank_frame = pd.read_csv(io.BytesIO(bank.read("bank-full.csv")), sep=";")
    write_samples(bank_frame, "bank", "y")
    with ZipFile(io.BytesIO(adult_zip)) as adult:
        names = adult_headers(adult.read("adult.names").decode("utf-8"))
        adult_frame = pd.read_csv(
            io.BytesIO(adult.read("adult.data")),
            names=names,
            skipinitialspace=True,
            na_values=["?"],
        )
    write_samples(adult_frame, "adult", "income")


if __name__ == "__main__":
    main()
