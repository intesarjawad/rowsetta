from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts import build_browser


@pytest.mark.native
def test_browser_wheel_contains_python_bytecode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build_browser, "PUBLIC", tmp_path)
    dependency = tmp_path / "dependency.whl"
    with ZipFile(dependency, "w") as wheel:
        wheel.writestr("sklearn/example.py", "value = 1\n")
    build_browser.package_core((dependency,))
    with ZipFile(tmp_path / build_browser.WHEEL) as wheel:
        assert "rowsetta/__pycache__/browser_shell.cpython-314.pyc" in wheel.namelist()
        assert "sklearn/__pycache__/example.cpython-314.pyc" in wheel.namelist()
