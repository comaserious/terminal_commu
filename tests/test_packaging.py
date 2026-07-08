import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_requirements_match_runtime_project_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    requirements = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert requirements == project["dependencies"]


def test_public_readme_has_portable_installation() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "/Users/hj/" not in readme
    assert "basic-env" not in readme
    assert "python3.12 -m venv .venv" in readme
    assert "py -3.12 -m venv .venv" in readme
    assert "python -m pip install -r requirements.txt" in readme
    assert "python -m pip install --no-deps ." in readme
    assert "python -m pip install -e '.[dev]'" in readme
    assert "python -m pytest -q" in readme
    assert "python -m ruff check ." in readme
