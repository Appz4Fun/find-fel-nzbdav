from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol
from urllib.parse import urlencode
from xml.etree import ElementTree

from models import Candidate


class TextHttpClient(Protocol):
    def get_text(self, url: str, timeout: float = 30) -> str: ...


class HydraError(ValueError):
    def __init__(self, code: str, description: str) -> None:
        self.code = code
        self.description = description
        super().__init__(f"Hydra error {code}: {description}")


REJECT_PATTERNS = (
    re.compile(r"\bmp4\b", re.IGNORECASE),
    re.compile(r"\bhdtv\b", re.IGNORECASE),
    re.compile(r"\bcam\b", re.IGNORECASE),
    re.compile(r"\btelesync\b", re.IGNORECASE),
)

FOUR_K_PATTERNS = (
    re.compile(r"\b2160p\b", re.IGNORECASE),
    re.compile(r"\buhd\b", re.IGNORECASE),
    re.compile(r"\b4k\b", re.IGNORECASE),
)

DV_PATTERNS = (
    re.compile(r"\bdolby[\s._-]+vision\b", re.IGNORECASE),
    re.compile(r"\bdovi\b", re.IGNORECASE),
    re.compile(r"\bdo[\s._-]+vi\b", re.IGNORECASE),
    re.compile(r"\bdv\b", re.IGNORECASE),
    re.compile(r"\bdvhe\b", re.IGNORECASE),
    re.compile(r"\bprofile[\s._-]+7\b", re.IGNORECASE),
)

WEB_DOWNLOAD_PATTERNS = (
    re.compile(r"\bweb[\s._-]?(?:dl|rip)\b", re.IGNORECASE),
    re.compile(r"\bwebrip\b", re.IGNORECASE),
)

BLURAY_LIKELY_PATTERNS = (
    re.compile(r"\bblu[\s._-]?ray\b", re.IGNORECASE),
    re.compile(r"\bbd[\s._-]?remux\b", re.IGNORECASE),
    re.compile(r"\bbd\b", re.IGNORECASE),
    re.compile(r"\bbr\b", re.IGNORECASE),
)

MKV_LIKELY_PATTERNS = (
    re.compile(r"\bmkv\b", re.IGNORECASE),
    re.compile(r"\bremux\b", re.IGNORECASE),
    *BLURAY_LIKELY_PATTERNS,
)
VIDEO_LIKELY_PATTERNS = MKV_LIKELY_PATTERNS + (
    re.compile(r"\bx265\b", re.IGNORECASE),
    re.compile(r"\bh[ ._-]?265\b", re.IGNORECASE),
    re.compile(r"\bhevc\b", re.IGNORECASE),
    re.compile(r"\bweb[ ._-]?dl\b", re.IGNORECASE),
)

MOVIES_HD_CATEGORY = "2040"
HYDRA_MIN_SIZE_MB = 3000
HYDRA_DEFAULT_LIMIT = 10000
TITLE_ACCEPT_AFTER_MATCH_TOKENS = {
    "2160p",
    "uhd",
    "blu",
    "bluray",
    "ray",
    "remux",
    "dv",
    "dovi",
    "dolby",
    "vision",
    "hdr",
    "hdr10",
    "hdr10plus",
    "hevc",
    "h265",
    "x265",
    "avc",
    "truehd",
    "atmos",
    "dts",
    "multi",
    "mult",
    "vfi",
    "vff",
    "vfq",
    "german",
    "french",
    "english",
    "japanese",
    "unrated",
    "extended",
    "theatrical",
    "directors",
    "director",
    "cut",
    "remastered",
    "complete",
}
TITLE_REJECT_AFTER_MATCH_TOKENS = {
    "collection",
    "trilogy",
    "duology",
    "quadrilogy",
    "saga",
    "pack",
    "part",
    "chapter",
    "volume",
    "vol",
    "season",
    "series",
}
ROMAN_NUMERAL_TOKENS = {
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "vii",
    "viii",
    "ix",
    "x",
}

KNOWN_QUERY_VARIANTS = {
    "hellboy animated": (
        "Hellboy Animated Sword of Storms",
        "Hellboy Animated Blood and Iron",
    ),
    "kin": ("Kin 2018",),
    "the conjuring 4 last rites": ("The Conjuring Last Rites",),
    "three colors": ("Three Colors Blue", "Three Colors White", "Three Colors Red"),
    "us": ("Us 2019",),
}
SKIP_ORIGINAL_QUERY_KEYS = {"kin", "us"}
QUERY_VARIANT_LIMIT_CAPS = {
    "kin 2018": 1000,
    "us 2019": 1000,
}


@dataclass(frozen=True)
class HydraSearchResult:
    raw_candidates: list[Candidate]
    candidates: list[Candidate]

    @property
    def raw_count(self) -> int:
        return len(self.raw_candidates)

    @property
    def has_4k_video(self) -> bool:
        return has_4k_video_candidate(self.raw_candidates)


def parse_hydra_results(xml_text: str) -> list[Candidate]:
    lowered = xml_text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("Hydra XML must not include document type or entity declarations")

    root = ElementTree.fromstring(xml_text)
    if _local_name(root.tag).lower() == "error":
        code = root.attrib.get("code", "unknown")
        description = root.attrib.get("description", "unknown error")
        raise HydraError(code, description)

    candidates: list[Candidate] = []
    for item in _iter_local(root, "item"):
        attributes = _newznab_attributes(item)
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        size_bytes = _parse_size(attributes.get("size"))
        candidates.append(
            Candidate(
                release_title=title,
                link=link,
                size_bytes=size_bytes,
                indexer=attributes.get("indexer"),
                pubdate=_child_text(item, "pubDate") or None,
                attributes=attributes,
            )
        )
    return candidates


def is_dv_4k_mkv_candidate(title: str) -> bool:
    if any(pattern.search(title) for pattern in REJECT_PATTERNS):
        return False
    if any(pattern.search(title) for pattern in WEB_DOWNLOAD_PATTERNS):
        return False
    return (
        any(pattern.search(title) for pattern in FOUR_K_PATTERNS)
        and any(pattern.search(title) for pattern in DV_PATTERNS)
        and any(pattern.search(title) for pattern in BLURAY_LIKELY_PATTERNS)
    )


def has_4k_video_candidate(candidates: list[Candidate]) -> bool:
    return any(is_4k_video_candidate(candidate.release_title) for candidate in candidates)


def is_4k_video_candidate(title: str) -> bool:
    if any(pattern.search(title) for pattern in REJECT_PATTERNS):
        return False
    return (
        any(pattern.search(title) for pattern in FOUR_K_PATTERNS)
        and any(pattern.search(title) for pattern in VIDEO_LIKELY_PATTERNS)
    )


def filter_and_rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    return sorted(
        (
            candidate
            for candidate in candidates
            if is_dv_4k_mkv_candidate(candidate.release_title)
        ),
        key=lambda candidate: candidate.size_bytes,
        reverse=True,
    )


def filter_title_matches(candidates: list[Candidate], query: str) -> list[Candidate]:
    return [
        candidate
        for candidate in candidates
        if release_title_matches_query(candidate.release_title, query)
    ]


def release_title_matches_query(release_title: str, query: str) -> bool:
    query_tokens = _strip_leading_article(_title_tokens(query))
    release_tokens = _strip_leading_article(_title_tokens(release_title))
    if not query_tokens or len(release_tokens) < len(query_tokens):
        return False
    if release_tokens[: len(query_tokens)] != query_tokens:
        return False
    remaining = release_tokens[len(query_tokens):]
    if not remaining:
        return True
    next_token = remaining[0]
    if next_token in TITLE_REJECT_AFTER_MATCH_TOKENS:
        return False
    if next_token.isdigit() and len(next_token) <= 2:
        return False
    if next_token in ROMAN_NUMERAL_TOKENS:
        return False
    return _is_year_token(next_token) or next_token in TITLE_ACCEPT_AFTER_MATCH_TOKENS


def search_hydra(
    http: TextHttpClient,
    hydra_url: str,
    api_key: str,
    query: str,
    *,
    limit: int = HYDRA_DEFAULT_LIMIT,
    timeout: float = 30,
) -> HydraSearchResult:
    raw_candidates: list[Candidate] = []
    first_error: Exception | None = None
    had_success = False

    for variant in query_variants(query):
        try:
            raw_candidates.extend(
                _search_hydra_variant(
                    http,
                    hydra_url,
                    api_key,
                    variant,
                    limit=_limit_for_query_variant(variant, limit),
                    timeout=timeout,
                )
            )
            had_success = True
        except Exception as exc:
            if first_error is None:
                first_error = exc

    if not had_success and first_error is not None:
        raise first_error

    raw_candidates = dedupe_hydra_candidates(raw_candidates)
    return HydraSearchResult(
        raw_candidates=raw_candidates,
        candidates=filter_and_rank_candidates(raw_candidates),
    )


def _search_hydra_variant(
    http: TextHttpClient,
    hydra_url: str,
    api_key: str,
    query: str,
    *,
    limit: int,
    timeout: float,
) -> list[Candidate]:
    params = urlencode(
        {
            "t": "movie",
            "q": normalize_hydra_query(query),
            "cat": MOVIES_HD_CATEGORY,
            "o": "xml",
            "limit": str(limit),
            "minsize": str(HYDRA_MIN_SIZE_MB),
            "apikey": api_key,
        }
    )
    url = f"{hydra_url.rstrip('/')}/api?{params}"
    raw_candidates = parse_hydra_results(http.get_text(url, timeout=timeout))
    return filter_title_matches(raw_candidates, query)


def query_variants(query: str) -> list[str]:
    variants: list[str] = []
    query_key = _query_key(query)
    variants.extend(KNOWN_QUERY_VARIANTS.get(query_key, ()))
    variants.extend(_repeated_and_title_variants(query))
    if query_key not in SKIP_ORIGINAL_QUERY_KEYS:
        variants.append(query)
    return _dedupe_strings(variants)


def _limit_for_query_variant(query: str, requested_limit: int) -> int:
    cap = QUERY_VARIANT_LIMIT_CAPS.get(_query_key(query))
    if cap is None:
        return requested_limit
    return min(requested_limit, cap)


def normalize_hydra_query(query: str) -> str:
    return re.sub(r"[`'’]", "", query).strip()


def dedupe_hydra_candidates(candidates: list[Candidate]) -> list[Candidate]:
    deduped: list[Candidate] = []
    seen: set[tuple[str, str, int]] = set()
    for candidate in candidates:
        key = (
            re.sub(r"[^a-z0-9]+", " ", candidate.release_title.lower()).strip(),
            candidate.link,
            candidate.size_bytes,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _title_tokens(title: str) -> list[str]:
    raw_tokens = re.findall(r"[a-z0-9]+", normalize_hydra_query(title).lower())
    tokens: list[str] = []
    for token in raw_tokens:
        if token == "s" and tokens:
            tokens[-1] = f"{tokens[-1]}s"
            continue
        tokens.append(token)
    return tokens


def _query_key(query: str) -> str:
    return " ".join(_title_tokens(query))


def _repeated_and_title_variants(query: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\s+and\s+", query, maxsplit=1, flags=re.IGNORECASE)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return []
    left_tokens = _title_tokens(parts[0])
    right_tokens = _title_tokens(parts[1])
    if not left_tokens or right_tokens[: len(left_tokens)] != left_tokens:
        return []
    return parts


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _query_key(value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _strip_leading_article(tokens: list[str]) -> list[str]:
    if tokens and tokens[0] == "the":
        return tokens[1:]
    return tokens


def _is_year_token(token: str) -> bool:
    if len(token) != 4 or not token.isdigit():
        return False
    year = int(token)
    return 1900 <= year <= 2099


def _newznab_attributes(item: ElementTree.Element) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for element in item.iter():
        if _local_name(element.tag) != "attr":
            continue
        name = element.attrib.get("name")
        value = element.attrib.get("value")
        if name is not None and value is not None:
            attributes[name] = value
    return attributes


def _child_text(item: ElementTree.Element, child_name: str) -> str:
    for child in item:
        if _local_name(child.tag).lower() == child_name.lower():
            return (child.text or "").strip()
    return ""


def _iter_local(root: ElementTree.Element, local_name: str):
    for element in root.iter():
        if _local_name(element.tag).lower() == local_name.lower():
            yield element


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_size(size: str | None) -> int:
    if not size:
        return 0
    try:
        return int(size)
    except ValueError:
        return 0
