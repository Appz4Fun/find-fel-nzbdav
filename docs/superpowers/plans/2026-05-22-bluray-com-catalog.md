# Blu-ray.com Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Blu-ray.com primary source path that lists physical 4K UHD Dolby Vision Blu-ray movie titles.

**Architecture:** Keep catalog scraping separate from the existing Hydra/NZBDAV FEL workflow. Add source-neutral catalog models and dedupe helpers, then add a Blu-ray.com source adapter, then expose it through a `catalog` CLI command that does not require `.env`.

**Tech Stack:** Python 3.11+ stdlib, `html.parser`, `urllib`, `json`, `pytest`, existing `uv run pytest` workflow.

---

## File Structure

- Create `src/find_fel_nzbdav/catalog.py`: source-neutral catalog dataclasses helpers, dedupe, JSON payload rendering.
- Create `src/find_fel_nzbdav/bluray_com.py`: Blu-ray.com URL construction, HTML parsing, optional cached fetching, and release discovery.
- Modify `src/find_fel_nzbdav/cli.py`: dispatch a new `catalog` subcommand before the existing title-check command path.
- Create `tests/test_catalog.py`: catalog dedupe and JSON payload tests.
- Create `tests/test_bluray_com.py`: parser, URL, cache, and source client tests with inline fixtures.
- Modify `tests/test_cli.py`: catalog command tests.

## Task 1: Source-Neutral Catalog Model

**Files:**
- Create: `src/find_fel_nzbdav/catalog.py`
- Test: `tests/test_catalog.py`

- [ ] **Step 1: Write failing catalog tests**

Create `tests/test_catalog.py`:

```python
from find_fel_nzbdav.catalog import (
    CatalogRelease,
    dedupe_catalog_titles,
    normalize_catalog_title,
    render_catalog_payload,
)


def test_normalizes_title_for_dedupe():
    assert normalize_catalog_title("The Deer Hunter 4K Blu-ray") == "deer hunter"
    assert normalize_catalog_title("Spider-Man: No Way Home") == "spider man no way home"


def test_dedupes_releases_by_title_and_year():
    releases = [
        CatalogRelease(
            source="bluray-com",
            source_id="1",
            source_url="https://www.blu-ray.com/movies/A-4K-Blu-ray/1/",
            title="The Deer Hunter",
            normalized_title="deer hunter",
            year=1978,
            country="United States",
            release_date="2018-05-22",
            edition="Standard",
            studio="Universal",
            video="Codec: HEVC / H.265; Resolution: 4K (2160p)",
            hdr="Dolby Vision, HDR10",
            discs="4K Ultra HD; Blu-ray Disc",
            is_4k=True,
            is_dolby_vision=True,
        ),
        CatalogRelease(
            source="bluray-com",
            source_id="2",
            source_url="https://www.blu-ray.com/movies/A-4K-Blu-ray/2/",
            title="The Deer Hunter 4K Blu-ray",
            normalized_title="deer hunter",
            year=1978,
            country="United Kingdom",
            release_date=None,
            edition="SteelBook",
            studio=None,
            video="Resolution: Native 4K (2160p)",
            hdr="Dolby Vision",
            discs="4K Ultra HD",
            is_4k=True,
            is_dolby_vision=True,
        ),
    ]

    titles = dedupe_catalog_titles(releases)

    assert len(titles) == 1
    assert titles[0].title == "The Deer Hunter"
    assert titles[0].year == 1978
    assert titles[0].release_count == 2
    assert titles[0].countries == ("United Kingdom", "United States")
    assert len(titles[0].source_urls) == 2
    assert titles[0].fel_status == "unknown"


def test_render_catalog_payload_can_include_releases():
    release = CatalogRelease(
        source="bluray-com",
        source_id="1",
        source_url="https://www.blu-ray.com/movies/A-4K-Blu-ray/1/",
        title="The Deer Hunter",
        normalized_title="deer hunter",
        year=1978,
        country="United States",
        release_date="2018-05-22",
        edition=None,
        studio=None,
        video="Resolution: 4K (2160p)",
        hdr="Dolby Vision",
        discs="4K Ultra HD",
        is_4k=True,
        is_dolby_vision=True,
    )

    payload = render_catalog_payload([release], include_releases=True)

    assert payload["source"] == "bluray-com"
    assert payload["count"] == 1
    assert payload["titles"][0]["title"] == "The Deer Hunter"
    assert payload["releases"][0]["source_id"] == "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_catalog.py -q`

Expected: FAIL because `find_fel_nzbdav.catalog` does not exist.

- [ ] **Step 3: Implement catalog module**

Create `src/find_fel_nzbdav/catalog.py` with:

- frozen `CatalogRelease` dataclass
- frozen `CatalogTitle` dataclass
- `normalize_catalog_title(title)`
- `dedupe_catalog_titles(releases)`
- `render_catalog_payload(releases, include_releases=False)`

Implementation rules:

- Remove suffixes like `4K Blu-ray`, `Blu-ray`, `UHD`, `Ultra HD`, and parenthesized edition text during normalization.
- Sort titles by normalized title then year.
- Preserve every supporting source URL.
- Set `fel_status` to `"unknown"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_catalog.py -q`

Expected: PASS.

## Task 2: Blu-ray.com Parser And Source Client

**Files:**
- Create: `src/find_fel_nzbdav/bluray_com.py`
- Test: `tests/test_bluray_com.py`

- [ ] **Step 1: Write failing Blu-ray.com tests**

Create `tests/test_bluray_com.py` with inline search/detail HTML fixtures. Tests must verify:

- `build_search_url(page=2)` returns `https://www.blu-ray.com/movies/search.php?action=search&ultrahd=1&dolbyvision=1&sortby=releasetimestamp&page=2`
- `parse_search_results(html)` returns unique detail URLs under `/movies/...-4K-Blu-ray/<id>/`
- `parse_release_detail(url, html)` extracts a `CatalogRelease`
- HDR10-only detail pages are parsed but classified with `is_dolby_vision=False`
- non-4K detail pages are parsed but classified with `is_4k=False`
- review prose mentioning Dolby Vision does not override the structured `HDR:` line
- `BlurayComSource.discover_releases(pages=1)` fetches search pages and detail pages and returns only `is_4k and is_dolby_vision` releases

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bluray_com.py -q`

Expected: FAIL because `find_fel_nzbdav.bluray_com` does not exist.

- [ ] **Step 3: Implement Blu-ray.com module**

Create `src/find_fel_nzbdav/bluray_com.py` with:

- `BLURAY_COM_BASE = "https://www.blu-ray.com"`
- `SOURCE_NAME = "bluray-com"`
- `build_search_url(page=1, sortby="releasetimestamp")`
- `parse_search_results(html, base_url=BLURAY_COM_BASE)`
- `parse_release_detail(url, html)`
- `class BlurayComSource`

Parser rules:

- Use stdlib `html.parser.HTMLParser`.
- Decode HTML entities with `html.unescape`.
- Extract detail URLs with a regex constrained to `/movies/...-4K-Blu-ray/<digits>/`.
- Extract `source_id` from the numeric URL suffix.
- Prefer `<meta property="og:title" content="...">` or `<title>` for the display title.
- Strip trailing country suffixes like `(United States)` from titles.
- Parse `country` from the final parenthesized value in the title/meta title when present.
- Parse structured `Video` and `Disc` sections by converting `<br>` to newlines and reading lines after `Video`, `Disc`, or `Discs` headings.
- Set `is_4k=True` only if video or discs include `4K`, `2160p`, `4K Ultra HD`, or `Ultra HD`.
- Set `is_dolby_vision=True` only if the structured `HDR:` value includes `Dolby Vision`.
- Do not search the full page prose for Dolby Vision.

`BlurayComSource` rules:

- Constructor accepts `http`, `cache_dir`, `country`, `delay_seconds`, and `sleeper`.
- Use `Cookie: country=<country>` when fetching if the provided HTTP object supports headers through construction; for tests, passing a fake object with `get_text(url, timeout=30)` is enough.
- Cache text responses under `cache_dir` by SHA-256 of URL + country.
- Fetch search page, extract detail URLs, fetch each detail page, parse, filter to `is_4k and is_dolby_vision`.
- Keep request sequencing single-threaded.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_bluray_com.py -q`

Expected: PASS.

## Task 3: CLI Catalog Command

**Files:**
- Modify: `src/find_fel_nzbdav/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Append tests to `tests/test_cli.py` that:

- call `main(["catalog", "--source", "bluray-com", "--json", "--pages", "1"], catalog_source=fake_source)`
- assert `.env` is not required
- assert JSON output includes title count and title rows
- call `main(["catalog", "--source", "bluray-com", "--output", "<tmp>/titles.json"], catalog_source=fake_source)`
- assert the output file is written

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -q`

Expected: FAIL because `main()` does not accept `catalog_source` and has no catalog subcommand.

- [ ] **Step 3: Implement CLI command**

Modify `src/find_fel_nzbdav/cli.py`:

- Add `build_catalog_parser()`.
- Add `main_catalog(argv, *, catalog_source=None)`.
- In `main()`, if first argument is `"catalog"`, route to `main_catalog()`.
- Add optional keyword `catalog_source=None` to `main()` for tests.
- Construct `BlurayComSource` with `HttpClient(headers={"User-Agent": "find-fel-nzbdav/0.1"})`, `cache_dir`, `country`, and `delay_seconds`.
- Render `render_catalog_payload(releases, include_releases=args.include_releases)` as pretty JSON.
- If `--output` is set, write the JSON there and print a short human-readable message.
- Return 0 when command completes.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -q`

Expected: PASS.

## Task 4: Verification And Review

**Files:**
- All touched files

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/test_catalog.py tests/test_bluray_com.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 3: Manual smoke command**

Run:

```bash
uv run find-fel-nzbdav catalog --source bluray-com --json --pages 0
```

Expected: exit 0 with an empty catalog JSON payload.

- [ ] **Step 4: Code review**

Dispatch a review agent with the plan and diff. Fix critical or important findings, then rerun full tests.
