import argparse
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class Dataset:
    """An immutable source archive, checked before entering the benchmark cache."""

    name: str
    uci_id: int
    slug: str
    sha256: str

    @property
    def url(self) -> str:
        """Use UCI's public archive endpoint without an account."""
        return f"https://archive.ics.uci.edu/static/public/{self.uci_id}/{self.slug}.zip"


# Source bytes and licences verified on 2026-11-05; see ADR 0009.
DATASETS = (
    Dataset(
        "dry_bean",
        602,
        "dry+bean+dataset",
        "0a64eff5be87f48c3dbbfc0a12a56c5d5b5167ef8e61cd45d69b3e7c7130c06f",
    ),
    Dataset(
        "mushroom",
        73,
        "mushroom",
        "face32f32647e0d939f6233f36dd30dd5d619ae9f3f9b8e10bea4ac7e1f60b1a",
    ),
    Dataset(
        "car",
        19,
        "car+evaluation",
        "1559d51dcf327f4f8c71b711ceed7fd95a382fc8d8e1998667f4f23b82860403",
    ),
)


def verify_archive(data: bytes, dataset: Dataset) -> None:
    """Reject changed or corrupt archives, including existing cache entries."""
    digest = hashlib.sha256(data).hexdigest()
    if digest != dataset.sha256:
        message = (
            f"dataset checksum mismatch: {dataset.name}; "
            f"expected {dataset.sha256}, got {digest}; remove its cached ZIP and retry"
        )
        raise SystemExit(message)
    print(f"{dataset.name}: {digest} ({len(data)} bytes)")


def main() -> None:
    """Populate the benchmark cache with checksum-verified UCI source archives."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify", action="store_true", help="verify all cached archives, fetching missing files"
    )
    parser.parse_args()
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    cache = cache_root / "rowsetta" / "bench"
    cache.mkdir(parents=True, exist_ok=True)
    for dataset in DATASETS:
        path = cache / f"{dataset.name}.zip"
        if path.exists():
            data = path.read_bytes()
        else:
            response = httpx.get(dataset.url, timeout=120, follow_redirects=True)
            response.raise_for_status()
            data = response.content
        verify_archive(data, dataset)
        if not path.exists():
            temporary = path.with_suffix(".zip.part")
            temporary.write_bytes(data)
            temporary.replace(path)
    print(f"Verified {len(DATASETS)} benchmark archives in {cache}")


if __name__ == "__main__":
    main()
