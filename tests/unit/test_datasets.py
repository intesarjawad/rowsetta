import hashlib
import io
from collections import Counter
from pathlib import Path

import httpx
import pandas as pd
import pytest

from scripts import fetch_datasets, fetch_model

DATASETS = Path(__file__).resolve().parents[2] / "src" / "rowsetta" / "datasets"


def test_penguins_is_the_unchanged_source_with_missing_markers() -> None:
    data = (DATASETS / "penguins.csv").read_bytes()

    assert hashlib.sha256(data).hexdigest() == fetch_datasets.PENGUINS_SHA256
    assert len(pd.read_csv(io.BytesIO(data))) == 344
    assert b",NA," in data


@pytest.mark.parametrize(("name", "target"), [("bank", "y"), ("adult", "income")])
def test_browser_samples_preserve_class_shares_and_come_from_local_files(
    name: str, target: str
) -> None:
    local = pd.read_csv(DATASETS / f"{name}.csv")
    browser = pd.read_csv(DATASETS / f"{name}_2k.csv")

    assert len(local) == 5_000
    assert len(browser) == 2_000
    local_shares = local[target].value_counts(normalize=True)
    browser_shares = browser[target].value_counts(normalize=True)
    assert set(local_shares.index) == set(browser_shares.index)
    assert (local_shares - browser_shares).abs().max() <= 0.005
    assert not (
        Counter(browser.to_csv(index=False).splitlines()[1:])
        - Counter(local.to_csv(index=False).splitlines()[1:])
    )
    expected = fetch_datasets.stratified_sample(local, target, 2_000).reset_index(drop=True)
    pd.testing.assert_frame_equal(browser, expected)


def test_bank_retains_duration_and_adult_maps_unknown_cells_to_missing() -> None:
    bank = pd.read_csv(DATASETS / "bank.csv")
    adult = pd.read_csv(DATASETS / "adult.csv")

    assert "duration" in bank.columns
    assert adult.shape == (5_000, 15)
    assert adult["workclass"].isna().any()
    assert not adult.isin(["?"]).any().any()
    assert list(adult.columns[-2:]) == ["native-country", "income"]


def test_dataset_source_drift_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def get_changed_source(url: str, *, timeout: int, follow_redirects: bool) -> httpx.Response:
        assert timeout > 0
        assert follow_redirects
        return httpx.Response(200, content=b"changed source", request=httpx.Request("GET", url))

    monkeypatch.setattr(fetch_datasets.httpx, "get", get_changed_source)

    with pytest.raises(SystemExit, match="dataset checksum mismatch"):
        fetch_datasets.download_verified(fetch_datasets.BANK_URL, fetch_datasets.BANK_SHA256)


@pytest.mark.parametrize("content", [b"corrupt", b"", b"x" * 1024])
def test_invalid_checkpoint_is_deleted(content: bytes, tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.ckpt"
    checkpoint.write_bytes(content)

    with pytest.raises(SystemExit) as caught:
        fetch_model.verify_checkpoint(checkpoint)

    assert caught.value.code == fetch_model.CHECKSUM_ERROR
    assert not checkpoint.exists()
