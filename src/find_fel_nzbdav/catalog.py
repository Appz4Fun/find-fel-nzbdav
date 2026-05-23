from __future__ import annotations

from dataclasses import asdict, dataclass
import re


@dataclass(frozen=True)
class CatalogRelease:
    source: str
    source_id: str
    source_url: str
    title: str
    normalized_title: str
    year: int | None
    country: str | None
    release_date: str | None
    edition: str | None
    studio: str | None
    video: str | None
    hdr: str | None
    discs: str | None
    is_4k: bool
    is_dolby_vision: bool
    fel_status: str = "unknown"


@dataclass(frozen=True)
class CatalogTitle:
    title: str
    normalized_title: str
    year: int | None
    release_count: int
    countries: tuple[str, ...]
    source_urls: tuple[str, ...]
    fel_status: str = "unknown"


_FORMAT_SUFFIX_RE = re.compile(
    r"(?:[\s:,-]+)?(?:4k\s+ultra\s+hd\s+blu[-\s]?ray|"
    r"4k\s+uhd\s+blu[-\s]?ray|uhd\s+blu[-\s]?ray|ultra\s+hd\s+blu[-\s]?ray|"
    r"4k\s+blu[-\s]?ray|blu[-\s]?ray|uhd|ultra\s+hd|4k)\s*$",
    re.IGNORECASE,
)


def normalize_catalog_title(title: str) -> str:
    normalized = re.sub(r"\([^)]*\)", " ", title.lower())
    while True:
        stripped = _FORMAT_SUFFIX_RE.sub("", normalized)
        if stripped == normalized:
            break
        normalized = stripped
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    normalized = re.sub(r"^the\s+", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def dedupe_catalog_titles(releases: list[CatalogRelease]) -> list[CatalogTitle]:
    grouped: dict[tuple[str, int | None], list[CatalogRelease]] = {}
    for release in releases:
        grouped.setdefault((release.normalized_title, release.year), []).append(release)

    titles = []
    for (normalized_title, year), group in grouped.items():
        titles.append(
            CatalogTitle(
                title=_choose_display_title(group),
                normalized_title=normalized_title,
                year=year,
                release_count=len(group),
                countries=tuple(
                    sorted({release.country for release in group if release.country})
                ),
                source_urls=tuple(
                    sorted({release.source_url for release in group if release.source_url})
                ),
            )
        )

    return sorted(titles, key=lambda title: (title.normalized_title, title.year or 0))


def render_catalog_payload(
    releases: list[CatalogRelease], include_releases: bool = False
) -> dict[str, object]:
    titles = dedupe_catalog_titles(releases)
    sources = {release.source for release in releases}
    payload: dict[str, object] = {
        "source": releases[0].source if len(sources) == 1 else "mixed",
        "count": len(titles),
        "titles": [asdict(title) for title in titles],
    }
    if include_releases:
        payload["releases"] = [asdict(release) for release in releases]
    return payload


def _choose_display_title(releases: list[CatalogRelease]) -> str:
    non_format_titles = [
        release.title
        for release in releases
        if normalize_catalog_title(release.title) == release.normalized_title
    ]
    candidates = non_format_titles or [release.title for release in releases]
    return min(candidates, key=lambda title: (len(title), title.lower()))
