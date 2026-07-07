# Multi-Community Reader Design

**Date:** 2026-07-07

## Goal

Turn the existing read-only FMKorea terminal reader into a three-site community
reader without duplicating the TUI. The primary `commu` command will support:

- the existing FMKorea overseas-football board;
- every publicly accessible DCInside general, minor, or mini gallery whose URL
  matches a supported desktop or mobile gallery form; and
- every publicly accessible Arca Live channel whose URL matches a supported
  board or article form.

Each site must provide board lists, article bodies, and comments when those
values are present in public HTML. Images, DCCons, and emoticons are represented
by text placeholders and are never downloaded for display.

## Non-goals

- Login, writing, voting, recommending, subscribing, or other state-changing
  operations.
- Adult verification, CAPTCHA, JavaScript/WASM challenge solving, or any other
  access-control bypass.
- A generic parser for arbitrary websites.
- Automatic background refresh, prefetching, or repeated retry loops.
- Preserving version-one cache entries. The first run after upgrading may need
  to fetch each board again.

## Command and startup experience

`commu` becomes the primary documented command. The existing `fmk` entry point
remains as a documented compatibility alias for existing installations.

Running `commu` without arguments opens a keyboard-driven launcher:

1. Choose FMKorea, DCInside, or Arca Live with Up/Down and Enter.
2. Choose `추천 URL 사용` or `URL 직접 입력` with Up/Down and Enter.
3. The direct-input path shows a URL input. Enter submits it and Escape returns
   to the previous launcher step.

The built-in recommendations are:

- FMKorea: `https://www.fmkorea.com/football_world`
- DCInside: `https://gall.dcinside.com/board/lists/?id=football_new9`
- Arca Live: `https://arca.live/b/rogersfu`

`commu <URL>` bypasses the launcher. A board URL opens the list. A direct
article URL opens that article and its comments; Back returns to the inferred
board. Unsupported or malformed URLs are rejected before any network request.

The reader retains the existing keys: arrows, Enter, Tab, Escape, `r`, and `q`.
Its title and status line show the active site and board/channel name rather
than the FMK-specific title.

## URL routing and validation

`UrlRouter` parses input into an immutable `CommunityTarget` containing the
site, canonical board identity, optional article identity, and canonical URL.
It accepts only HTTPS, rejects embedded credentials, strips fragments, and
allows only the following host/path families:

- FMKorea: `www.fmkorea.com` and the existing overseas-football board/article
  forms already supported by the application.
- DCInside desktop: `gall.dcinside.com` general, `mgallery`, and `mini` list and
  view paths with valid `id` and, for articles, numeric `no` parameters.
- DCInside mobile: `m.dcinside.com/board/<gallery>` and
  `m.dcinside.com/board/<gallery>/<article>`.
- Arca Live: `arca.live/b/<channel>` and
  `arca.live/b/<channel>/<numeric-article>`.

Gallery and channel names are treated as opaque identifiers after strict
character and length validation. Unknown query parameters are discarded when
building canonical fetch URLs. Redirects may stay only within the adapter's
explicit origin allowlist; cross-site redirects fail.

## Adapter architecture

The reader uses a site adapter selected by `UrlRouter`. A `CommunityAdapter`
interface owns all site-dependent behavior:

- recognizing and canonicalizing targets;
- naming the active board/channel;
- producing paginated list and article URLs;
- defining request headers, allowed origins, request spacing, and rate-limit
  status codes;
- parsing board HTML into common post summaries; and
- parsing article HTML into a common body and comment page.

`FmkAdapter` wraps the existing FMK parser and URL rules. `DcinsideAdapter`
accepts desktop URLs but fetches canonical mobile pages with a mobile User-Agent
because the public mobile article HTML contains the body and server-rendered
comments in one read-only response. `ArcaAdapter` reads board, body, and comments
from public server-rendered Arca HTML.

Post and comment identifiers become opaque strings in the common model. Site
and board identities live in `CommunityTarget` and service context, so identical
numeric article IDs on different sites cannot collide.

## Service, HTTP, and cache flow

`CommunityService` replaces FMK-specific URL construction while preserving the
existing cache-first behavior:

1. Ask the selected adapter for a cache key and canonical fetch URL.
2. Return a fresh cache entry unless refresh was explicitly requested.
3. Ask the adapter-aware HTTP client for one serialized fetch.
4. Parse and validate that the returned page belongs to the requested site,
   board, and article before writing it to cache.
5. On a fetch failure, return a stale entry when one exists; otherwise surface
   the typed error to the UI.

Version-two cache keys include site and board identity, for example
`v2:dcinside:football_new9:board:1` and
`v2:arca:rogersfu:post:176096992:comments:1`.

Each adapter has an explicit request policy. Fetches remain serialized and
start at least two seconds apart. HTTP 429 and FMKorea HTTP 430 responses use
`Retry-After` to establish a local cooldown. While cooling down, refresh and
navigation that require a new request fail locally with the remaining wait
time; no request is sent. There is no automatic retry. FMK challenge HTML,
403 responses, and other supported-site challenge pages are typed access
errors and may use stale cache only.

Cookies are not imported from a browser and challenge tokens are not generated.
The DCInside mobile User-Agent is a representation choice for the site's public
mobile HTML, not an authentication or challenge bypass.

## TUI components and state

The Textual application gains a `LauncherScreen` and keeps one shared reader
screen. The launcher owns only site selection and URL entry. It hands a
validated `CommunityTarget` to the reader, which then creates the adapter,
service, and site-specific request policy.

Reader workers continue to commit page state only after successful loads and
coalesce repeated navigation. Switching sites replaces reader state, cancels
old workers, and closes old resources before opening the new target. Literal
remote text remains `markup=False` everywhere.

Media nodes are converted by adapters into placeholders:

- ordinary images and videos: `[이미지]` and `[동영상]`;
- DCInside DCCons: `[디시콘]`;
- Arca emoticons: `[이모티콘]`.

Reply depth is preserved where public HTML exposes it. The shared UI may indent
replies but does not attempt to reconstruct relationships that a site omits.

## Error handling

- URL validation errors identify the unsupported host or path and return to the
  launcher without sending a request.
- Parse errors include the site name and never cache partially parsed data.
- A requested/returned board or article identity mismatch is rejected before
  cache writes.
- Rate-limit notices show the remaining cooldown and whether stale content is
  being displayed.
- A direct article with no usable cache shows an error but keeps the application
  responsive so Escape can return to its board or launcher.
- Resource cleanup is exception-safe across launcher transitions and shutdown.

## Testing and verification

All parsing tests are fixture-driven and make no live requests. Fixtures cover:

- FMKorea regression behavior;
- DCInside desktop/mobile URL normalization, general/minor/mini galleries,
  notices/ads filtering, body text, media placeholders, comments, replies, and
  pagination;
- Arca board/channel routing, notices filtering, body text, media placeholders,
  comments, replies, and pagination;
- malformed and cross-site URLs, redirect restrictions, identity mismatches,
  429/430 cooldown behavior, stale cache, and site-separated cache keys; and
- launcher navigation, URL entry, direct CLI URLs, direct article startup,
  back behavior, site titles, and preserved reader keyboard controls.

The complete existing suite must continue to pass. Final verification also
includes Ruff, package import, both `commu` and compatibility `fmk` command
discovery, and one conservative live smoke read per site. Live checks perform
no repeated retry and stop on rate limit or challenge responses.

## Documentation and rollout

README examples use `commu`, document the launcher and `commu <URL>`, list all
supported URL families, explain the `fmk` compatibility alias, and state the
read-only/no-bypass policy. The editable package is reinstalled in `basic-env`
after integration so both console entry points resolve to the Desktop project.
