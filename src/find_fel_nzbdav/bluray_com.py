from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import hashlib
import re
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode, urljoin, urlsplit

from find_fel_nzbdav.catalog import CatalogRelease, normalize_catalog_title


BLURAY_COM_BASE = "https://www.blu-ray.com"
SOURCE_NAME = "bluray-com"

_DETAIL_PATH_RE = re.compile(r"^/movies/[^\"'<>]*-4K-Blu-ray/(\d+)/?$")
_HREF_RE = re.compile(r"""\bhref\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)
_META_TITLE_RE = re.compile(
    r"""<meta\b(?=[^>]*\bproperty\s*=\s*["']og:title["'])(?=[^>]*\bcontent\s*=\s*(["'])(.*?)\1)[^>]*>""",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_COUNTRY_SUFFIX_RE = re.compile(r"\s*\(([^()]*)\)\s*$")
_FORMAT_SUFFIX_RE = re.compile(r"(?:[\s:,-]+)?4K\s+Blu[-\s]?ray\s*$", re.IGNORECASE)
_HDR_LINE_RE = re.compile(r"^HDR\s*:\s*(.+)$", re.IGNORECASE)
_FOUR_K_RE = re.compile(r"\b(?:4K|2160p|4K\s+Ultra\s+HD|Ultra\s+HD)\b", re.IGNORECASE)


class TextHttpClient(Protocol):
    def get_text(self, url: str, timeout: float = 30) -> str: ...


def build_search_url(page: int = 1, sortby: str = "releasetimestamp") -> str:
    query = urlencode(
        {
            "action": "search",
            "ultrahd": "1",
            "dolbyvision": "1",
            "sortby": sortby,
            "page": str(page),
        }
    )
    return f"{BLURAY_COM_BASE}/movies/search.php?{query}"


def parse_search_results(html: str, base_url: str = BLURAY_COM_BASE) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in _HREF_RE.finditer(unescape(html)):
        href = match.group(2).strip()
        parts = urlsplit(href)
        if parts.scheme and parts.netloc.lower() != urlsplit(base_url).netloc.lower():
            continue
        path = parts.path
        if not _DETAIL_PATH_RE.match(path):
            continue
        url = urljoin(base_url, path)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def parse_release_detail(url: str, html: str) -> CatalogRelease:
    title_text = _extract_display_title(html)
    country = _extract_country(title_text)
    title = _clean_release_title(title_text)
    sections = _SectionParser.parse(html)
    video = _section_text(sections, "video")
    discs = _section_text(sections, "discs") or _section_text(sections, "disc")
    hdr = _extract_hdr(video)
    year = _extract_year(_section_text(sections, "year") or title_text)
    release_date = _section_text(sections, "release date")
    edition = _section_text(sections, "edition")
    studio = _section_text(sections, "studio")
    structured_4k_text = "\n".join(part for part in (video, discs) if part)

    return CatalogRelease(
        source=SOURCE_NAME,
        source_id=_source_id_from_url(url),
        source_url=url,
        title=title,
        normalized_title=normalize_catalog_title(title),
        year=year,
        country=country,
        release_date=release_date or None,
        edition=edition or None,
        studio=studio or None,
        video=video or None,
        hdr=hdr,
        discs=discs or None,
        is_4k=bool(_FOUR_K_RE.search(structured_4k_text)),
        is_dolby_vision=bool(hdr and re.search(r"\bDolby\s+Vision\b", hdr, re.IGNORECASE)),
        fel_status="unknown",
    )


class BlurayComSource:
    def __init__(
        self,
        http: TextHttpClient,
        cache_dir: str | Path | None = None,
        country: str = "all",
        delay_seconds: float = 10.0,
        sleeper=time.sleep,
        timeout: float = 30,
    ) -> None:
        self.http = http
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.country = country
        self.delay_seconds = delay_seconds
        self.sleeper = sleeper
        self.timeout = timeout
        self._configure_headers()

    def discover_releases(self, pages: int = 1) -> list[CatalogRelease]:
        if pages <= 0:
            return []

        releases: list[CatalogRelease] = []
        for page in range(1, pages + 1):
            search_html = self.fetch_text(build_search_url(page=page))
            for detail_url in parse_search_results(search_html):
                detail_html = self.fetch_text(detail_url)
                release = parse_release_detail(detail_url, detail_html)
                if release.is_4k and release.is_dolby_vision:
                    releases.append(release)
        return releases

    def fetch_text(self, url: str) -> str:
        cache_path = self._cache_path(url)
        if cache_path is not None and cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        text = self.http.get_text(url, timeout=self.timeout)
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
        if self.delay_seconds > 0:
            self.sleeper(self.delay_seconds)
        return text

    def _cache_path(self, url: str) -> Path | None:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha256(f"{url}\n{self.country}".encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.html"

    def _configure_headers(self) -> None:
        headers = getattr(self.http, "headers", None)
        if not isinstance(headers, dict):
            return
        headers.setdefault("User-Agent", "find-fel-nzbdav/bluray-com")
        headers.setdefault("Cookie", f"country={self.country}")


class _SectionParser(HTMLParser):
    _HEADINGS = {"h1", "h2", "h3", "h4", "strong", "b"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: dict[str, list[str]] = {}
        self._current_heading: str | None = None
        self._capturing_heading: str | None = None
        self._heading_parts: list[str] = []
        self._line_parts: list[str] = []

    @classmethod
    def parse(cls, html: str) -> dict[str, str]:
        parser = cls()
        parser.feed(html)
        parser.close()
        parser._flush_line()
        return {
            heading: "\n".join(line for line in lines if line).strip()
            for heading, lines in parser.sections.items()
        }

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self._HEADINGS or _is_subheading_span(tag, attrs):
            self._capturing_heading = tag
            self._heading_parts = []
        elif tag == "br":
            self._flush_line()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._capturing_heading == tag:
            heading = _normalize_space(" ".join(self._heading_parts)).lower()
            if heading:
                self._flush_line()
                self._current_heading = heading
                self.sections.setdefault(heading, [])
            self._capturing_heading = None
            self._heading_parts = []
        elif tag in {"p", "div", "li", "tr"}:
            self._flush_line()

    def handle_data(self, data: str) -> None:
        text = unescape(data)
        if self._capturing_heading is not None:
            self._heading_parts.append(text)
        elif self._current_heading is not None:
            self._line_parts.append(text)

    def _flush_line(self) -> None:
        if self._current_heading is None:
            self._line_parts = []
            return
        line = _normalize_space(" ".join(self._line_parts))
        if line:
            self.sections.setdefault(self._current_heading, []).append(line)
        self._line_parts = []


def _extract_display_title(html: str) -> str:
    meta = _META_TITLE_RE.search(html)
    if meta:
        return _normalize_space(unescape(meta.group(2)))
    title = _TITLE_RE.search(html)
    if title:
        return _normalize_space(_TAG_RE.sub(" ", unescape(title.group(1))))
    return ""


def _extract_country(title: str) -> str | None:
    match = _COUNTRY_SUFFIX_RE.search(title)
    return match.group(1).strip() if match else None


def _clean_release_title(title: str) -> str:
    title = _COUNTRY_SUFFIX_RE.sub("", title).strip()
    while True:
        stripped = _FORMAT_SUFFIX_RE.sub("", title).strip(" :-,")
        if stripped == title:
            return title
        title = stripped


def _source_id_from_url(url: str) -> str:
    match = _DETAIL_PATH_RE.match(urlsplit(url).path)
    if not match:
        raise ValueError(f"Not a Blu-ray.com 4K movie detail URL: {url}")
    return match.group(1)


def _section_text(sections: dict[str, str], heading: str) -> str | None:
    return sections.get(heading)


def _extract_hdr(video: str | None) -> str | None:
    if not video:
        return None
    for line in video.splitlines():
        match = _HDR_LINE_RE.match(line)
        if match:
            return match.group(1).strip()
    return None


def _extract_year(text: str) -> int | None:
    match = _YEAR_RE.search(text)
    return int(match.group(1)) if match else None


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_subheading_span(tag: str, attrs) -> bool:
    if tag != "span":
        return False
    return any(
        name.lower() == "class" and "subheading" in value.split()
        for name, value in attrs
        if isinstance(value, str)
    )
