# Final Fix Report

Date: 2026-07-07 (Asia/Seoul)

## Status and SHAs

- Review base: `965f25e` (`docs: correct media placeholders`)
- Implementation commit: `2e3f5d9` (`fix: close final multi-community review gaps`)
- Status: all requested final-review fixes implemented and verified.

## Implemented fixes

- Added `CommunityRequestState` containing the lock, last request start, and `Retry-After` deadline, plus a process-lifetime `RequestStateRegistry` keyed by `Site`.
- Kept `CommunityHttpClient` isolated by default for unit/direct callers; the default resource factory explicitly supplies the shared per-site state.
- Proved same-site client recreation cannot bypass two-second spacing, FMK HTTP 430 cooldown survives close/reselection with zero second-client requests, different sites receive different state objects, and redirect hops remain spaced.
- Added FMK response-board validation before parsing/caching. Accepted markers are same-origin canonical URLs, board title links, category links carrying `mid`, and board-pagination hidden `mid` values. Numeric article IDs alone never establish board identity.
- Added real-semantics fixture markers and wrong-board tests for both board lists and direct numeric articles; service tests prove no post/body cache writes on mismatch.
- Site-qualified every FMK adapter `ParseError` with `FMKorea`.
- Set reader title/subtitle context atomically from `adapter.site_name` and `target.board_id`; FMKorea, DCInside, and Arca tests prove the prefix survives board and post updates.
- Added Arca HTTP/cross-origin row and article identity rejection tests, preserved nested wrapper depth greater than one, and added a launcher mouse-selection regression.
- Retained stale-generation resources whose first cleanup attempt fails, reported the failure, retried only the still-open handle during unmount, and propagated a repeated cleanup failure.

## One-response FMK structural evidence

Exactly one public request was made, with no retry and redirects disabled:

```text
curl --silent --show-error --max-time 15 --max-redirs 0 \
  --output /private/tmp/fmk-current-board.html \
  --dump-header /private/tmp/fmk-current-board.headers \
  https://www.fmkorea.com/football_world
exit=0
HTTP/2 200
body bytes: 77770
```

Observed identity structures included:

```text
var current_mid = "football_world";
window.currentBoardMid = "football_world";
<link rel="canonical" href="https://www.fmkorea.com/football_world" />
<a href="/football_world">...</a>
<a href="/index.php?mid=football_world&category=...">...</a>
<form class="bd_pg ..."><input type="hidden" name="mid" value="football_world" />
```

The implementation deliberately relies on the HTML link/input markers, not JavaScript variables, and accepts multiple redundant real-page forms for compatibility.

## RED evidence

The initial valid-environment client collection failed because the required state API did not exist:

```text
conda run -n basic-env pytest -q tests/test_client.py tests/test_adapters.py \
  tests/test_service.py tests/test_app.py tests/test_arca_adapter.py \
  tests/test_launcher.py

ImportError: cannot import name 'CommunityRequestState' from 'fmk_reader.client'
1 error in 0.23s
```

Running the other new regressions before production edits produced the expected behavior failures:

```text
12 failed, 72 passed in 14.54s
```

The failures proved:

- wrong-board and missing-marker FMK HTML parsed without error;
- FMK parser errors lacked the site prefix;
- reader title/subtitles lost site/board context;
- the default resource factory passed no shared state;
- stale cleanup errors were silent and not retained;
- nested Arca wrappers were capped at depth one.

The initial mouse test used the OptionList border coordinate (`y=0`), which carries no `style.meta["option"]`; source inspection of Textual's `_on_click` distinguished this test-coordinate issue from an implementation failure. Selecting actual option rows (`y=1` and `y=3`) passed.

## GREEN evidence

Focused client/app/FMK/Arca/launcher/service suite after final edits:

```text
conda run -n basic-env pytest -q tests/test_client.py tests/test_adapters.py \
  tests/test_service.py tests/test_app.py tests/test_arca_adapter.py \
  tests/test_launcher.py
........................................................................ [ 57%]
.....................................................                    [100%]
125 passed in 15.13s
```

Full suite after final edits:

```text
conda run -n basic-env pytest -q
........................................................................ [ 33%]
........................................................................ [ 67%]
....................................................................     [100%]
212 passed in 15.19s
```

Ruff:

```text
conda run -n basic-env ruff check .
All checks passed!
exit=0
```

Byte compilation:

```text
conda run -n basic-env python -m compileall -q src tests
exit=0
```

Dependency integrity:

```text
conda run -n basic-env python -m pip check
WARNING: The directory '/Users/hj/Library/Caches/pip' or its parent directory is not owned or is not writable by the current user. The cache has been disabled.
No broken requirements found.
exit=0
```

Whitespace/error-marker check:

```text
git diff --check
exit=0
```

## Remaining concerns

- No functional concern remains from the final review findings.
- The single allowed live response was a board page, not a post page. Compatibility is protected by accepting redundant FMK board/category/canonical markers and fixture-driven direct-article tests; no second live request was made.
- If a retained stale resource also fails during the bounded unmount retry, shutdown now raises that cleanup error instead of hiding it.
