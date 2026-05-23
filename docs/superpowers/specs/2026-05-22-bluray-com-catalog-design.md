# Blu-ray.com Catalog Design

## Goal

Add a Blu-ray.com-backed catalog path that lists movie titles with physical 4K UHD Blu-ray releases that explicitly include Dolby Vision.

This catalog is separate from the existing Hydra/NZBDAV FEL probe. Blu-ray.com metadata can prove "4K UHD Dolby Vision Blu-ray"; it does not prove FEL or MEL.

## Operating Assumption

The user has stated they have permission/responsibility to use Blu-ray.com as a primary scrape source. The implementation will still keep the source explicit, rate-limited, cached, and attributable.

## Data Model

The pipeline keeps release rows separate from deduped movie titles.

`CatalogRelease` represents one physical Blu-ray.com release/SKU:

- `source`
- `source_id`
- `source_url`
- `title`
- `normalized_title`
- `year`
- `country`
- `release_date`
- `edition`
- `studio`
- `video`
- `hdr`
- `discs`
- `is_4k`
- `is_dolby_vision`
- `fel_status`

`CatalogTitle` represents a deduped movie title:

- `title`
- `normalized_title`
- `year`
- `release_count`
- `countries`
- `source_urls`
- `fel_status`

Deduping is by normalized title + year for this first implementation. TMDb matching can be added later without changing the release parser.

## Blu-ray.com Source

The primary discovery URL is:

`https://www.blu-ray.com/movies/search.php?action=search&ultrahd=1&dolbyvision=1&sortby=releasetimestamp`

Pagination uses `page=N`. Country scope is represented by a request cookie, usually `country=all` for worldwide coverage.

The source adapter has three layers:

1. URL construction for search pages.
2. Search-result parsing to discover detail page URLs.
3. Detail-page parsing to extract structured release fields and classify 4K Dolby Vision eligibility.

The parser only trusts detail-page spec sections such as `Video`, `Disc`/`Discs`, and release metadata. It must not mark a release Dolby Vision because random review/news prose mentions Dolby Vision.

## CLI

The existing `find-fel-nzbdav <title>` command remains unchanged.

A new catalog command is added:

```bash
find-fel-nzbdav catalog --source bluray-com --json
```

Useful options:

- `--country all`
- `--pages N`
- `--cache-dir .cache/bluray-com`
- `--delay-seconds 10`
- `--output data/titles.json`
- `--include-releases`

The catalog command must not require `.env`, Hydra, NZBDAV, or WebDAV settings.

## Output

Default JSON output is title-level:

```json
{
  "source": "bluray-com",
  "count": 1,
  "titles": [
    {
      "title": "The Deer Hunter",
      "year": 1978,
      "release_count": 1,
      "countries": ["United States"],
      "source_urls": ["https://www.blu-ray.com/movies/.../"],
      "fel_status": "unknown"
    }
  ]
}
```

With `--include-releases`, output also includes the release rows that supported each title.

## Caching And Rate Limiting

The implementation uses a simple on-disk text cache keyed by URL and country cookie. When a cached response exists, it is reused. When a page is fetched from the network, the client sleeps for `delay_seconds` before the next request.

The implementation avoids login, collection, community, link redirect, and purchase endpoints.

## Testing

Tests use small HTML fixtures that model Blu-ray.com search and detail pages. They cover:

- search URL construction
- detail URL extraction and de-duplication
- detail parsing for title, product id, country, year, HDR, video, discs, release date, and edition
- rejecting HDR10-only 4K pages
- rejecting non-4K Blu-ray pages
- deduping multiple releases into one title
- CLI catalog JSON without `.env`

No live Blu-ray.com scrape is required for the unit test suite.

## Non-Goals

- TMDb canonicalization.
- FEL/MEL proof from Blu-ray.com metadata.
- Submitting scraped titles to NZBDAV automatically.
- Concurrent high-volume crawling.
