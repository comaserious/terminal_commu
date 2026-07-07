# Final Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the final whole-branch review findings without expanding the approved three-community reader scope.

**Architecture:** Move request serialization and cooldown timestamps into explicit per-site state objects supplied to transient HTTP clients by a process-lifetime registry. Validate FMK response board identity at the adapter boundary before parsing or caching, keep a stable site/board label in every reader title and subtitle, and retain stale-generation resources whose first cleanup attempt fails so unmount can retry them.

**Tech Stack:** Python 3.12, asyncio, httpx 0.28, Beautiful Soup 4.14, Textual 8.2, pytest, Ruff.

## Global Constraints

- Preserve two-second spacing for every request and redirect hop, including across same-site client recreation.
- Preserve HTTP 429 and FMKorea HTTP 430 `Retry-After` cooldown across same-site client recreation; sites remain independent.
- Reject FMK board/article responses lacking a trustworthy `football_world` board marker before cache writes.
- Prefix FMK adapter parse errors with `FMKorea` and keep site/board context visible through board and article updates.
- Keep all remote requests read-only and do not add retry or challenge-bypass behavior.

---

### Task 1: Process-lifetime per-site request state

**Files:**
- Modify: `src/fmk_reader/client.py`
- Modify: `src/fmk_reader/app.py`
- Test: `tests/test_client.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Produces: `CommunityRequestState` and `RequestStateRegistry.state_for(site)`.
- Consumes: `CommunityHttpClient(..., state=None)` with isolated state for ordinary callers; `create_reader_resources` supplies the default registry's state.

- [ ] Add failing tests that recreate an FMK client with shared state and prove spacing and 430 cooldown survive, while Arca state remains independent.
- [ ] Run the focused client/app tests and record expected early-request failures.
- [ ] Move lock, last-started time, and retry deadline into the supplied state and wire the default resource factory to the process registry.
- [ ] Re-run focused client/app tests and keep redirect-hop tests green.

### Task 2: FMK returned-board identity validation

**Files:**
- Modify: `tests/fixtures/board.html`
- Modify: `tests/fixtures/post.html`
- Modify: `src/fmk_reader/adapters/fmk.py`
- Test: `tests/test_adapters.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes real FMK canonical board links and category links containing `mid=football_world`.
- Produces adapter-level `ParseError` messages prefixed with `FMKorea`.

- [ ] Add fixture identity markers and failing board/direct-article mismatch tests, including no-cache-write assertions.
- [ ] Run focused adapter/service tests and confirm wrong-board HTML currently parses.
- [ ] Extract only trusted canonical, board-title, pagination-mid, and category-link identities; reject missing or mismatched identities before parser calls.
- [ ] Wrap remaining parser errors once at the FMK adapter boundary and rerun focused tests.

### Task 3: Persistent reader context

**Files:**
- Modify: `src/fmk_reader/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Produces: a stable context label from `adapter.site_name` and `target.board_id` used by the app title and every committed board/post subtitle.

- [ ] Add failing FMK/DCInside/Arca activation tests plus board/post update assertions.
- [ ] Set context only when activation commits atomically and prefix loading, board, post, and failure status text.
- [ ] Re-run app tests and verify launcher/reset behavior remains intact.

### Task 4: Bounded low-severity regressions and cleanup retry

**Files:**
- Modify: `src/fmk_reader/adapters/arca.py`
- Modify: `src/fmk_reader/app.py`
- Test: `tests/test_arca_adapter.py`
- Test: `tests/test_launcher.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Produces exact nested wrapper depth; stale-generation cleanup records retry only the handles that failed.

- [ ] Add Arca HTTP/cross-origin identity tests, a depth-two wrapper test, and a launcher mouse-selection test.
- [ ] Add a failing stale-generation cleanup test proving the exception is reported and the failed handle is retried during unmount.
- [ ] Implement exact wrapper depth and retained cleanup records with a bounded retry at unmount.
- [ ] Re-run Arca, launcher, and app tests.

### Task 5: Verification and handoff

**Files:**
- Create: `.superpowers/sdd/final-fix-report.md`

- [ ] Run focused client/app/FMK/Arca/launcher/service tests.
- [ ] Run full `pytest`, Ruff, `compileall`, `pip check`, and `git diff --check`.
- [ ] Write RED/GREEN evidence, exact outputs, commit SHAs, the one-response FMK marker evidence, and remaining concerns to the report.
- [ ] Commit the coherent fix wave and report.
