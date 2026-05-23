from __future__ import annotations

import re
from typing import Protocol
from urllib.parse import urlencode
from xml.etree import ElementTree

from models import Candidate


class TextHttpClient(Protocol):
    def get_text(self, url: str, timeout: float = 30) -> str: ...


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

MKV_LIKELY_PATTERNS = (
    re.compile(r"\bmkv\b", re.IGNORECASE),
    re.compile(r"\bremux\b", re.IGNORECASE),
    re.compile(r"\bblu[\s._-]?ray\b", re.IGNORECASE),
    re.compile(r"\buhd\b", re.IGNORECASE),
)


def parse_hydra_results(xml_text: str) -> list[Candidate]:
    lowered = xml_text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("Hydra XML must not include document type or entity declarations")

    root = ElementTree.fromstring(xml_text)
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
    return (
        any(pattern.search(title) for pattern in FOUR_K_PATTERNS)
        and any(pattern.search(title) for pattern in DV_PATTERNS)
        and any(pattern.search(title) for pattern in MKV_LIKELY_PATTERNS)
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


def search_hydra(
    http: TextHttpClient,
    hydra_url: str,
    api_key: str,
    query: str,
    *,
    limit: int = 100,
    timeout: float = 30,
) -> list[Candidate]:
    params = urlencode(
        {
            "t": "search",
            "q": query,
            "o": "xml",
            "limit": str(limit),
            "apikey": api_key,
        }
    )
    url = f"{hydra_url.rstrip('/')}/api?{params}"
    return filter_and_rank_candidates(parse_hydra_results(http.get_text(url, timeout=timeout)))


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
