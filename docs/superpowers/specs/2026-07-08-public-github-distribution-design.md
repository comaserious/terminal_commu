# Public GitHub Distribution Design

**Date:** 2026-07-08

## Goal

Make the repository usable by people who clone or download it from GitHub,
without relying on the original developer's absolute filesystem path or Conda
environment name.

## Audience and language

The README remains Korean-first because the application reads Korean community
sites. Commands must be copyable by a user with basic terminal familiarity.
The primary audience is an end user installing from source; contributor setup
is documented separately.

## Runtime requirements

- Python `>=3.12,<3.13`.
- A terminal that supports the Textual interface.
- Network access to the selected public community page.

Conda is optional. The public instructions use Python's built-in `venv` so the
repository does not depend on a locally named `basic-env` environment.

## Dependency file

Create a root `requirements.txt` containing runtime dependencies only, with the
same ranges as `[project].dependencies` in `pyproject.toml`:

```text
beautifulsoup4>=4.14,<5
httpx>=0.28,<0.29
textual>=8.2,<9
```

Test dependencies remain in the `dev` optional dependency group and do not
belong in `requirements.txt`.

Add an offline packaging test that reads both files and asserts exact runtime
dependency equality. This prevents the two declarations from silently
diverging.

## Public installation flow

The README explains that users may clone the repository from GitHub's `Code`
menu or download and extract a ZIP. It then gives platform-specific virtual
environment activation commands.

macOS/Linux:

```bash
cd terminal_community
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --no-deps .
commu
```

Windows PowerShell:

```powershell
cd terminal_community
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --no-deps .
commu
```

`pip install --no-deps .` installs the package and console scripts after the
runtime dependencies have been installed from `requirements.txt`. The README
also notes that users must reactivate `.venv` in each new terminal session.

## README structure

The public README contains:

1. A concise description and read-only/no-bypass statement.
2. Supported sites and main features.
3. Python and terminal prerequisites.
4. Clone/ZIP and cross-platform installation instructions.
5. `commu` launcher and `commu <URL>` examples.
6. Supported URL families and all keyboard controls.
7. Cache, media placeholders, request spacing, cooldown, and challenge behavior.
8. Troubleshooting for `commu` not found, wrong Python version, HTTP 403/429/430,
   and challenge pages.
9. Contributor installation with `python -m pip install -e '.[dev]'` plus test
   and Ruff commands.

Remove the original developer's absolute Desktop path and the requirement to
activate `basic-env`. Do not include a fabricated GitHub owner/repository URL;
the GitHub `Code` menu instruction works before the final repository URL is
known.

## Verification

- The dependency-sync test must first fail without `requirements.txt`, then
  pass after it is created.
- The complete existing test suite and Ruff must pass.
- Build an isolated package installation in a temporary virtual environment
  using the documented dependency/install sequence when network/package cache
  availability permits.
- Verify `commu` and compatibility alias `fmk` are both installed.
- Search README for the original absolute path and `basic-env`; neither may
  remain in end-user instructions.

No application runtime behavior changes in this work.
