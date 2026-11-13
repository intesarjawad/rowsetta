"""Run the headed, adapter-asserted local browser parity and latency harness."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    subprocess.run(  # noqa: S603 -- Fixed local benchmark entrypoint.
        [shutil.which("node") or "node", "scripts/browser_spike.mjs"], cwd=ROOT, check=True
    )
