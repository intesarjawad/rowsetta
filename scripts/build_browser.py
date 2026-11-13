"""Package only the browser core and pinned runtime, never local model/server code."""

import base64
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile

from rowsetta.browser_shell import BrowserShell, browser_metadata
from rowsetta.core.lite_teacher import LiteTeacher
from scripts.mirror_onnx import stage

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "frontend/public/browser"
RUNTIME_VERSION = "314.0.7"
PACKAGES = ("numpy", "pandas", "scipy", "scikit-learn", "pydantic", "micropip")
WHEEL = "rowsetta_browser_core-0.1.0-py3-none-any.whl"


def package_core(dependencies: tuple[Path, ...]) -> None:
    """Build a pure wheel without invoking the full application's frontend hook."""
    package = ROOT / "src/rowsetta"
    files = [
        package / "__init__.py",
        package / "browser_shell.py",
        *sorted((package / "core").rglob("*.py")),
    ]
    sources = {
        path.relative_to(ROOT / "src").as_posix(): path.read_text(encoding="utf-8")
        for path in files
    }
    for dependency in dependencies:
        with ZipFile(dependency) as archive:
            for name in archive.namelist():
                if (
                    name.startswith(("pandas/", "sklearn/"))
                    and name.endswith(".py")
                    and "/tests/" not in name
                ):
                    sources[name] = archive.read(name).decode("utf-8")
    # Compile with Pyodide itself so bytecode matches its pinned Python ABI.
    compiler = r"""
import { loadPyodide } from './frontend/node_modules/pyodide/pyodide.mjs';
const py = await loadPyodide({indexURL: './frontend/node_modules/pyodide/'});
let sources = '';
for await (const chunk of process.stdin) sources += chunk;
py.globals.set('sources_json', sources);
console.log(py.runPython(`
import base64, importlib.util, json, pathlib, py_compile
sources = json.loads(sources_json)
root = pathlib.Path('/tmp/rowsetta-compile')
result = {}
for name, source in sources.items():
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    cache = importlib.util.cache_from_source(name)
    output = root / cache
    output.parent.mkdir(parents=True, exist_ok=True)
    py_compile.compile(str(path), cfile=str(output), dfile=name, doraise=True,
                       invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
    result[cache] = base64.b64encode(output.read_bytes()).decode('ascii')
json.dumps(result)
`));
"""
    node = shutil.which("node")
    if node is None:
        msg = "Node.js is required to compile the browser wheel"
        raise FileNotFoundError(msg)
    compiled = subprocess.run(  # noqa: S603 -- Node and script are fixed build inputs.
        [node, "--input-type=module", "-e", compiler],
        input=json.dumps(sources),
        stdout=subprocess.PIPE,
        text=True,
        check=True,
        cwd=ROOT,
    )
    bytecode = json.loads(compiled.stdout)
    with ZipFile(PUBLIC / WHEEL, "w", ZIP_DEFLATED) as wheel:
        for path in files:
            wheel.write(path, path.relative_to(ROOT / "src"))
        for name, encoded in bytecode.items():
            wheel.writestr(name, base64.b64decode(encoded))
        metadata = "rowsetta_browser_core-0.1.0.dist-info"
        for name in ("LICENSE", "NOTICE"):
            wheel.write(ROOT / name, f"{metadata}/licenses/{name}")
        wheel.writestr(
            f"{metadata}/METADATA",
            "Metadata-Version: 2.1\nName: rowsetta-browser-core\nVersion: 0.1.0\n",
        )
        wheel.writestr(
            f"{metadata}/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        )
        wheel.writestr(f"{metadata}/RECORD", "")


def stage_teacher() -> None:
    """Serve verified weights and ONNX Runtime from the same static origin."""
    stage(PUBLIC / "weights")
    ort = next(
        (ROOT / "frontend/node_modules/.pnpm").glob(
            "onnxruntime-web@*/node_modules/onnxruntime-web/dist"
        )
    )
    (PUBLIC / "ort").mkdir(exist_ok=True)
    for name in ("ort-wasm-simd-threaded.jsep.mjs", "ort-wasm-simd-threaded.jsep.wasm"):
        shutil.copyfile(ort / name, PUBLIC / "ort" / name)


def main() -> None:
    """Stage a self-contained runtime so visitor data never needs a remote service."""
    PUBLIC.mkdir(parents=True, exist_ok=True)
    stage_teacher()
    runtime = ROOT / "frontend/node_modules/pyodide"
    lock = json.loads((runtime / "pyodide-lock.json").read_text())
    selected: set[str] = set()

    def include(name: str) -> None:
        name = name.replace("_", "-")
        if name in selected:
            return
        selected.add(name)
        for dependency in lock["packages"][name]["depends"]:
            include(dependency)

    for package in PACKAGES:
        include(package)
    destination = PUBLIC / "runtime"
    destination.mkdir(exist_ok=True)
    for name in (
        "pyodide.mjs",
        "pyodide.asm.mjs",
        "pyodide.asm.wasm",
        "python_stdlib.zip",
        "pyodide-lock.json",
    ):
        shutil.copyfile(runtime / name, destination / name)
    for name in sorted(selected):
        entry = lock["packages"][name]
        path = runtime / entry["file_name"]
        if not path.exists():
            with urlopen(
                f"https://cdn.jsdelivr.net/pyodide/v{RUNTIME_VERSION}/full/{path.name}"
            ) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                msg = f"Runtime checksum mismatch: {name}"
                raise ValueError(msg)
            path.write_bytes(data)
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            msg = f"Runtime checksum mismatch: {path}"
            raise ValueError(msg)
        shutil.copyfile(path, destination / path.name)
    package_core(
        tuple(
            destination / lock["packages"][name]["file_name"] for name in ("pandas", "scikit-learn")
        )
    )
    shutil.copyfile(ROOT / "src/rowsetta/datasets/penguins.csv", PUBLIC / "penguins.csv")
    shell = BrowserShell(LiteTeacher(), browser_metadata("2026-11-11"))
    shell.workspace.load((PUBLIC / "penguins.csv").read_bytes(), "penguins.csv", max_rows=2000)
    shell.workspace.set_target("species", ("Adelie", "Chinstrap", "Gentoo"))
    (PUBLIC / "demo.json").write_text(
        json.dumps(
            {
                "state": shell.state(),
                "table": shell.table_page(0, 1000),
                "session": json.loads(shell.workspace.require_store().to_json()),
            }
        )
    )
    manifest = {
        str(path.relative_to(PUBLIC)): {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(PUBLIC.rglob("*"))
        if path.is_file() and path.name not in ("manifest.json", "demo.json")
    }
    (PUBLIC / "manifest.json").write_text(json.dumps(manifest))
    total = sum(path.stat().st_size for path in PUBLIC.rglob("*") if path.is_file())
    print(f"Browser runtime and core: {total} bytes")


if __name__ == "__main__":
    main()
