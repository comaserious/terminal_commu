# Commu Product Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every product-level `fmk` name with `commu`, leave only FMKorea-specific adapter names, and install only the `commu` CLI.

**Architecture:** Rename the Python package and distribution atomically so code never supports two product namespaces. Keep site-specific `FmkAdapter` identifiers, create a fresh cache under `~/.cache/commu`, and document explicit removal of the old distribution because pip cannot infer a rename.

**Tech Stack:** Python 3.12, Hatchling, Textual, httpx, SQLite, pytest, Ruff

## Global Constraints

- Python requirement remains `>=3.12,<3.13`.
- Runtime dependency ranges remain identical to `requirements.txt`.
- Only console script `commu` is installed; no `fmk` compatibility command.
- Distribution and import package are both named `commu`.
- FMKorea-only names `FmkAdapter`, `Site.FMKOREA`, and `adapters/fmk.py` remain.
- Cache starts fresh at `~/.cache/commu/cache.db`; old cache is neither read, moved, nor deleted.
- Preserve unrelated user changes.

---

### Task 1: Rename Distribution and Python Package

**Files:**
- Rename: `src/fmk_reader/` to `src/commu/`
- Modify: `pyproject.toml`
- Modify: every `src/commu/**/*.py` import
- Modify: every `tests/test_*.py` import
- Test: `tests/test_packaging.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: existing `fmk_reader.app:main` package layout
- Produces: import package `commu`, distribution `commu`, console script mapping `commu = "commu.app:main"`

- [ ] **Step 1: Write failing packaging tests**

Add to `tests/test_packaging.py`:

```python
def test_project_uses_commu_distribution_and_module() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert config["project"]["name"] == "commu"
    assert config["project"]["scripts"] == {"commu": "commu.app:main"}
    assert config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/commu"
    ]
    assert (ROOT / "src" / "commu").is_dir()
    assert not (ROOT / "src" / "fmk_reader").exists()
```

Replace the command assertion in `tests/test_cli.py` with:

```python
def test_project_exposes_only_commu_command() -> None:
    scripts = tomllib.loads(Path("pyproject.toml").read_text())["project"]["scripts"]

    assert scripts == {"commu": "commu.app:main"}
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
conda run -n basic-env pytest tests/test_packaging.py::test_project_uses_commu_distribution_and_module tests/test_cli.py::test_project_exposes_only_commu_command -v
```

Expected: both fail because distribution, module, and scripts still use `fmk-reader` or `fmk_reader`.

- [ ] **Step 3: Rename package and imports**

Perform mechanical rename:

```bash
git mv src/fmk_reader src/commu
```

Replace every import prefix in `src/commu` and `tests`:

```text
fmk_reader -> commu
```

Set exact packaging fields in `pyproject.toml`:

```toml
[project]
name = "commu"

[project.scripts]
commu = "commu.app:main"

[tool.hatch.build.targets.wheel]
packages = ["src/commu"]
```

Do not rename `src/commu/adapters/fmk.py`, `FmkAdapter`, `Site.FMKOREA`, FMKorea URLs, or FMKorea parsing errors.

- [ ] **Step 4: Run renamed package tests and verify GREEN**

Run:

```bash
conda run -n basic-env pytest tests/test_packaging.py tests/test_cli.py -v
conda run -n basic-env pytest -q
```

Expected: packaging/CLI tests pass, then all 214 or more tests pass.

- [ ] **Step 5: Verify old module references are absent**

Run:

```bash
rg -n "fmk_reader" src tests pyproject.toml
```

Expected: no matches, exit code 1.

- [ ] **Step 6: Commit atomic package rename**

```bash
git add pyproject.toml src tests
git commit -m "refactor: rename package to commu"
```

### Task 2: Rename Product Runtime Identity

**Files:**
- Modify: `src/commu/app.py`
- Modify: `src/commu/adapters/fmk.py`
- Modify: `src/commu/adapters/dcinside.py`
- Modify: `src/commu/adapters/arca.py`
- Modify: `tests/test_app.py`
- Modify: `tests/test_adapters.py`
- Modify: `tests/test_dcinside_adapter.py`
- Modify: `tests/test_arca_adapter.py`

**Interfaces:**
- Consumes: renamed `commu` package from Task 1
- Produces: `default_cache_path(home: Path | None = None) -> Path`, common User-Agent `commu/0.1 personal read-only client`

- [ ] **Step 1: Write failing cache-path test**

Import `default_cache_path` from `commu.app` in `tests/test_app.py`, then add:

```python
def test_default_cache_path_uses_commu_product_name() -> None:
    assert default_cache_path(Path("/home/test")) == Path(
        "/home/test/.cache/commu/cache.db"
    )
```

- [ ] **Step 2: Update User-Agent expectations before implementation**

Change product-level policy assertions in `tests/test_adapters.py`,
`tests/test_dcinside_adapter.py`, and `tests/test_arca_adapter.py` to exact value:

```python
assert adapter.policy.user_agent == "commu/0.1 personal read-only client"
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
conda run -n basic-env pytest tests/test_app.py::test_default_cache_path_uses_commu_product_name tests/test_adapters.py::test_fmk_adapter_exposes_strict_request_policy tests/test_dcinside_adapter.py tests/test_arca_adapter.py -q
```

Expected: collection fails because `default_cache_path` is missing, or assertions fail on old User-Agent.

- [ ] **Step 4: Implement fresh Commu cache path**

Add to `src/commu/app.py`:

```python
def default_cache_path(home: Path | None = None) -> Path:
    base = Path.home() if home is None else home
    return base / ".cache" / "commu" / "cache.db"
```

Change resource creation to:

```python
cache = JsonCache(default_cache_path())
```

Do not inspect or alter `~/.cache/fmk-reader`.

- [ ] **Step 5: Implement common User-Agent**

Set every community `RequestPolicy.user_agent` to:

```python
"commu/0.1 personal read-only client"
```

Keep all site display names and allowed origins unchanged.

- [ ] **Step 6: Run focused and full tests**

Run:

```bash
conda run -n basic-env pytest tests/test_app.py::test_default_cache_path_uses_commu_product_name tests/test_adapters.py tests/test_dcinside_adapter.py tests/test_arca_adapter.py -q
conda run -n basic-env pytest -q
```

Expected: all focused tests and full suite pass.

- [ ] **Step 7: Commit runtime identity rename**

```bash
git add src/commu tests
git commit -m "refactor: use commu runtime identity"
```

### Task 3: Update Public Installation and Upgrade Documentation

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Consumes: new distribution and CLI from Tasks 1-2
- Produces: portable clean-install and old-distribution removal instructions

- [ ] **Step 1: Write failing README contract assertions**

Extend `test_public_readme_has_portable_installation` in
`tests/test_packaging.py`:

```python
assert "기존 `fmk` 명령" not in readme
assert "python -m pip uninstall fmk-reader" in readme
assert "~/.cache/commu/cache.db" in readme
assert "~/.cache/fmk-reader/cache.db" not in readme
```

Add:

```python
def test_pyproject_is_not_ignored() -> None:
    ignored = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "pyproject.toml" not in ignored
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
conda run -n basic-env pytest tests/test_packaging.py -v
```

Expected: README assertions fail on old alias/cache text; ignore assertion fails only if the latest branch contains the bad ignore rule.

- [ ] **Step 3: Update README and ignore rules**

Remove `fmk` compatibility alias text. Change documented cache to
`~/.cache/commu/cache.db`. Add upgrade section:

```bash
python -m pip uninstall fmk-reader
python -m pip install -r requirements.txt
python -m pip install --no-deps .
commu --help
```

Explain that old cache is not reused or deleted. Remove `pyproject.toml` from
`.gitignore` if present; do not change unrelated ignore entries.

- [ ] **Step 4: Run documentation tests**

```bash
conda run -n basic-env pytest tests/test_packaging.py -v
git diff --check
```

Expected: all packaging tests pass; no whitespace errors.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md .gitignore tests/test_packaging.py
git commit -m "docs: document commu installation and upgrade"
```

### Task 4: Verify Clean Installation and Remove Legacy Command

**Files:**
- Verify only: whole repository

**Interfaces:**
- Consumes: completed renamed package
- Produces: evidence that only `commu` installs in a clean Python 3.12 environment

- [ ] **Step 1: Run static and test verification**

```bash
conda run -n basic-env pytest -q
conda run -n basic-env ruff check .
conda run -n basic-env python -m compileall -q src tests
conda run -n basic-env python -m pip check
git diff --check
```

Expected: all tests pass, Ruff reports `All checks passed!`, compileall exits 0,
pip reports `No broken requirements found.`, diff check exits 0.

- [ ] **Step 2: Build and install in a clean Python 3.12 venv**

Create a temporary venv, then run README sequence:

```bash
python3.12 -m venv /tmp/commu-clean-install
/tmp/commu-clean-install/bin/python -m pip install -r requirements.txt
/tmp/commu-clean-install/bin/python -m pip install --no-deps .
```

If shell `python3.12` is unavailable, use the exact Python 3.12 interpreter from
`basic-env` only to create the venv.

Expected: wheel name starts with `commu-0.1.0`; installation succeeds.

- [ ] **Step 3: Verify entry points and import namespace**

```bash
/tmp/commu-clean-install/bin/commu --help
/tmp/commu-clean-install/bin/python -c "import commu; print(commu.__file__)"
test ! -e /tmp/commu-clean-install/bin/fmk
```

Expected: `commu --help` exits 0, import path contains `site-packages/commu`, and
no `fmk` executable exists.

- [ ] **Step 4: Verify allowed remaining FMK names**

```bash
rg -n "fmk-reader|fmk_reader" src tests pyproject.toml README.md
rg -n "FmkAdapter|Site\.FMKOREA|adapters\.fmk|www\.fmkorea\.com" src tests
```

Expected: first command has no source/package matches except README uninstall
instruction `fmk-reader`; second command shows only FMKorea-specific code.

- [ ] **Step 5: Confirm clean branch state**

```bash
git status --short
git log -4 --oneline
```

Expected: clean worktree; rename, runtime identity, and documentation commits
appear after design/plan commits.
