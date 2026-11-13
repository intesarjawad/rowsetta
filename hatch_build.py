"""Build the web interface into the package, so one install serves the whole app."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

PNPM_MISSING = (
    "Building the rowsetta wheel needs Node 26 and pnpm on PATH to build its web "
    "interface. Next: install Node 26 and pnpm, or run `uv pip install -e .` for an "
    "editable install that serves the API without the interface."
)


class FrontendBuildHook(BuildHookInterface[Any]):
    """Run the Vite build into `src/rowsetta/static` before packaging."""

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Build the interface, unless this is an editable install or an unpacked sdist."""
        del build_data
        # `uv sync` and `uv pip install -e .` build editable wheels, which must not need Node.
        if version == "editable":
            return
        root = Path(self.root)
        frontend = root / "frontend"
        if not frontend.is_dir():
            # An sdist carries the built interface instead of its sources.
            index = root / "src" / "rowsetta" / "static" / "index.html"
            if not index.is_file():
                msg = f"{index} is missing from this source distribution."
                raise RuntimeError(msg)
            return
        pnpm = shutil.which("pnpm")
        if pnpm is None:
            raise RuntimeError(PNPM_MISSING)
        subprocess.run([pnpm, "--dir", frontend, "install", "--frozen-lockfile"], check=True)  # noqa: S603
        subprocess.run([pnpm, "--dir", frontend, "build"], check=True)  # noqa: S603
