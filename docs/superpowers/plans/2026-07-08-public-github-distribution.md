# Public GitHub Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide Korean public installation documentation and a runtime-only `requirements.txt` so GitHub users can install Commu without the original developer's path or Conda environment.

**Architecture:** Keep `pyproject.toml` as package metadata and mirror only its runtime dependency ranges into `requirements.txt`. An offline packaging test enforces equality, while README presents cross-platform source installation, usage, troubleshooting, and contributor workflows.

**Tech Stack:** Python 3.12, `venv`, pip, TOML via Python 3.12 `tomllib`, pytest, Markdown.

## Global Constraints

- README is Korean-first.
- Python requirement is exactly `>=3.12,<3.13`.
- `requirements.txt` contains runtime dependencies only: Beautiful Soup, httpx, and Textual with the exact ranges from `pyproject.toml`.
- End-user instructions must not require `/Users/hj/...` or Conda `basic-env`.
- macOS/Linux and Windows PowerShell virtual-environment instructions are required.
- Installation order is `pip install -r requirements.txt` followed by `pip install --no-deps .`.
- Existing `commu` and compatibility `fmk` commands remain unchanged.
- No runtime application behavior changes.

---

### Task 1: Public README and synchronized runtime requirements

**Files:**
- Create: `requirements.txt`
- Create: `tests/test_packaging.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `[project].dependencies`, `[project].requires-python`, and `[project.scripts]` from `pyproject.toml`.
- Produces: a runtime dependency file, public installation guide, and offline drift tests.

- [ ] **Step 1: Write failing packaging and README tests**

```python
# tests/test_packaging.py
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
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n basic-env pytest tests/test_packaging.py -v`

Expected: one test errors because `requirements.txt` does not exist and the README portability test fails on `/Users/hj/` and `basic-env`.

- [ ] **Step 3: Create the exact runtime requirements file**

```text
# requirements.txt
beautifulsoup4>=4.14,<5
httpx>=0.28,<0.29
textual>=8.2,<9
```

- [ ] **Step 4: Rewrite README installation and public-project sections**

Keep the existing accurate site, URL, key, cache, placeholder, request-spacing,
and challenge-policy sections. Replace the local install block and add these
sections in this order:

1. `# Commu`
2. `## 주요 기능` with FMKorea, DCInside, Arca Live, list/body/comments,
   direct URLs, cache, and read-only bullets.
3. `## 요구사항` with Python 3.12 and terminal/network requirements.
4. `## 설치` explaining GitHub `Code` clone or ZIP download.
5. `### macOS / Linux` with the exact commands below.
6. `### Windows PowerShell` with the exact commands below.
7. Existing execution, recommended URL, supported URL, key, and policy sections.
8. `## 문제 해결` covering inactive virtual environments, Python version,
   HTTP 403/429/430, and JavaScript/WASM challenge behavior.
9. `## 개발 및 테스트` with the exact contributor commands below.

```bash
# macOS / Linux
cd terminal_community
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --no-deps .
commu
```

```powershell
# Windows PowerShell
cd terminal_community
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --no-deps .
commu
```

```bash
# contributor workflow
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
```

State that `.venv` must be reactivated in each new terminal. Do not fabricate a
GitHub owner/repository URL or add badges that point to nonexistent services.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `conda run -n basic-env pytest tests/test_packaging.py -v`

Expected: both packaging tests pass.

- [ ] **Step 6: Run complete offline verification**

Run: `conda run -n basic-env pytest -q`

Expected: the complete suite passes.

Run: `conda run -n basic-env ruff check .`

Expected: `All checks passed!`

Run: `git diff --check`

Expected: exit code 0 with no output.

- [ ] **Step 7: Verify a clean temporary installation when dependencies are available**

Run in a temporary directory outside the repository:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r '/Users/hj/Documents/터미널로 웹검색하기/.isolated/terminal-community-fmk-reader/requirements.txt'
.venv/bin/python -m pip install --no-deps '/Users/hj/Documents/터미널로 웹검색하기/.isolated/terminal-community-fmk-reader'
.venv/bin/commu --help
```

Expected: installation succeeds and `commu --help` exits 0. If package-index
network access is unavailable, report the exact blocked command and retain the
offline dependency-sync test as deterministic evidence.

- [ ] **Step 8: Commit public distribution files**

```bash
git add README.md requirements.txt tests/test_packaging.py
git commit -m "docs: add public GitHub installation"
```
