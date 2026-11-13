import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(
  new URL("../frontend/package.json", import.meta.url),
);
const { loadPyodide } = require("pyodide");
const root = fileURLToPath(new URL("../", import.meta.url));
const py = await loadPyodide();
await py.loadPackage([
  "pandas",
  "scikit-learn",
  "scipy",
  "numpy",
  "pytest",
  "pydantic",
  "micropip",
  "jsonschema",
]);
await py.runPythonAsync(
  "import pandas, sklearn, scipy, numpy, pytest, pydantic, jsonschema",
);
// Hypothesis is pure Python; native-only tests are deselected after collection.
await py.runPythonAsync(
  "import micropip; await micropip.install('hypothesis==6.170.14')",
);
py.FS.mkdir("/repo");
py.FS.mount(py.FS.filesystems.NODEFS, { root }, "/repo");
const status = await py.runPythonAsync(`
import os, sys, pytest
os.chdir('/repo')
sys.path.insert(0, '/repo/src')
pytest.main(['tests/unit', '-m', 'not native', '--confcutdir=tests/unit'])
`);
process.exitCode = status;
