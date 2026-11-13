import huggingface_hub

from rowsetta.teachers.checkpoint import (
    CHECKSUM_ERROR,
    FILENAME,
    SHA256,
    ModelHub,
    checkpoint_path,
    verify_checkpoint,
)

__all__ = ["CHECKSUM_ERROR", "main", "verify_checkpoint"]


def main(hub: ModelHub = huggingface_hub) -> None:
    """Fetch the pinned public checkpoint and print its verified location."""
    path = checkpoint_path(hub)
    print(f"{FILENAME}: {SHA256} ({path.stat().st_size} bytes)")
    print(path)


if __name__ == "__main__":
    main()
