"""Stage the reviewed browser model locally; upload only with an explicit flag."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from huggingface_hub import HfApi

REPO = "bakshinghampalace/tabicl-classifier-v2-onnx"
REVISION = "098fb7be8df8a853a9d7f54a344ee9c6734a53d1"
FILES = {
    "onnx/model_fp16w.onnx": "8bf7d1a8c5859c596a3056afb637e2a5c2529b8a6e6bf538ac61792773ff8baa",
    "onnx/model_fp16w.f16": "3378b112ed579a28c2b7d40991c7bfb5fecfab2e126e7c2edfe47799863173c4",
}

FP32 = {"onnx/model.onnx": "bbe7e2d3023f94fd4546545e57dac77bc2853b38de4f87638fc3d040d7833be0"}


def stage(folder: Path, *, fp32: bool = False) -> None:
    """Verify cached and newly downloaded files against the reviewed archive pins."""
    files = FILES | FP32 if fp32 else FILES
    for name in ("config.json", "README.md", *files):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with urlopen(f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}") as response:
                data = response.read()
            if name in files and hashlib.sha256(data).hexdigest() != files[name]:
                msg = f"Checksum mismatch: {name}"
                raise ValueError(msg)
            path.write_bytes(data)
        if name in files and hashlib.sha256(path.read_bytes()).hexdigest() != files[name]:
            msg = f"Checksum mismatch: {path}"
            raise ValueError(msg)
    config = json.loads((folder / "config.json").read_text())
    for name, digest in files.items():
        if config["files"][name]["sha256"] != digest:
            msg = f"Config does not preserve pin: {name}"
            raise ValueError(msg)
    print(f"Verified local ONNX files in {folder}")


def main() -> None:
    """Stage locally unless the maintainer explicitly requests an upload."""
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--local", type=Path, required=True, help="local staging directory")
    cli.add_argument(
        "--upload", metavar="ACCOUNT/REPO", help="explicit maintainer-requested mirror upload"
    )
    cli.add_argument(
        "--fp32", action="store_true", help="also stage the pinned diagnostic fp32 graph"
    )
    args = cli.parse_args()
    stage(args.local, fp32=args.fp32)
    if args.upload:
        api = HfApi()
        api.create_repo(args.upload, exist_ok=True)
        result = api.upload_folder(repo_id=args.upload, folder_path=args.local)
        print(f"Mirror revision: {result.oid}")


if __name__ == "__main__":
    main()
