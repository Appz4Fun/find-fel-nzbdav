from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree


class PropfindHttpClient(Protocol):
    def propfind(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 10,
    ) -> str: ...


class WebDavClient:
    def __init__(
        self,
        headers: dict[str, str] | None = None,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.headers = headers or {}
        self.opener = opener

    def propfind(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 10,
    ) -> str:
        request = Request(
            url,
            headers={**self.headers, "Depth": "infinity", **(headers or {})},
            method="PROPFIND",
        )
        with self.opener(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset)


@dataclass(frozen=True)
class WebDavFile:
    path: str
    name: str
    size_bytes: int


def basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def find_largest_mkv(
    http: PropfindHttpClient,
    webdav_url: str,
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 10,
) -> WebDavFile | None:
    headers = basic_auth_header(username, password) if username and password else {}
    xml_text = http.propfind(
        _join_url(webdav_url, path),
        headers=headers,
        timeout=timeout,
    )

    files = [
        file
        for file in _parse_propfind_files(xml_text)
        if unquote(file.path).lower().endswith(".mkv")
    ]
    if not files:
        return None
    return max(files, key=lambda file: file.size_bytes)


def join_webdav_url(webdav_url: str, href_or_path: str) -> str:
    base = webdav_url.rstrip("/")
    href = urlsplit(href_or_path)
    raw_path = href.path if href.scheme and href.netloc else href_or_path
    path = quote(raw_path.strip("/"), safe="/%")
    if not path:
        return f"{base}/"

    base_path = urlsplit(base).path.strip("/")
    if base_path and path == base_path:
        return f"{base}/"
    if base_path and path.startswith(f"{base_path}/"):
        origin = base[: -len(base_path)].rstrip("/")
        return f"{origin}/{path}"
    return f"{base}/{path}"


def _parse_propfind_files(xml_text: str) -> list[WebDavFile]:
    lowered = xml_text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("WebDAV XML must not include document type or entity declarations")

    root = ElementTree.fromstring(xml_text)
    files: list[WebDavFile] = []
    for response in _iter_local(root, "response"):
        href = _first_descendant_text(response, "href")
        if not href:
            continue
        size = _parse_int(_first_descendant_text(response, "getcontentlength"))
        files.append(
            WebDavFile(
                path=href,
                name=_file_name_from_href(href),
                size_bytes=size,
            )
        )
    return files


def _join_url(base_url: str, path: str) -> str:
    return join_webdav_url(base_url, path).rstrip("/") + "/"


def _file_name_from_href(href: str) -> str:
    parsed = urlsplit(href)
    path = parsed.path or href
    return unquote(path.rstrip("/").rsplit("/", 1)[-1])


def _first_descendant_text(element: ElementTree.Element, local_name: str) -> str:
    for descendant in element.iter():
        if _local_name(descendant.tag).lower() == local_name.lower():
            return (descendant.text or "").strip()
    return ""


def _iter_local(root: ElementTree.Element, local_name: str):
    for element in root.iter():
        if _local_name(element.tag).lower() == local_name.lower():
            yield element


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0
