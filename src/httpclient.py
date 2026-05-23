from __future__ import annotations

import json
import re
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


SECRET_QUERY_KEYS = {
    "apikey",
    "api_key",
    "key",
    "token",
    "access_token",
    "password",
    "passwd",
    "pass",
}


class HttpClient:
    def __init__(self, headers: dict[str, str] | None = None, opener=urlopen) -> None:
        self.headers = headers or {}
        self.opener = opener

    def get_text(self, url: str, timeout: float = 30) -> str:
        request = Request(url, headers=self.headers)
        with self.opener(request, timeout=timeout) as response:
            body = response.read()
            charset = response.headers.get_content_charset() or _html_meta_charset(body) or "utf-8"
            try:
                return body.decode(charset, errors="replace")
            except LookupError:
                return body.decode("utf-8", errors="replace")

    def get_bytes(self, url: str, timeout: float = 30) -> bytes:
        request = Request(url, headers=self.headers)
        with self.opener(request, timeout=timeout) as response:
            return response.read()

    def get_json(self, url: str, timeout: float = 30):
        return json.loads(self.get_text(url, timeout=timeout))

    def post_multipart_json(
        self,
        url: str,
        *,
        field_name: str,
        filename: str,
        data: bytes,
        timeout: float = 30,
    ):
        boundary = f"----find-fel-nzbdav-{uuid.uuid4().hex}"
        body = _multipart_body(boundary, field_name, filename, data)
        headers = {
            **self.headers,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        }
        request = Request(url, data=body, headers=headers, method="POST")
        with self.opener(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    netloc = parts.netloc
    if parts.username is not None:
        host = parts.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        netloc = f"<redacted>@{host}"
    query = parse_qsl(parts.query, keep_blank_values=True)
    redacted_query = [
        (key, "<redacted>" if key.lower() in SECRET_QUERY_KEYS else _redact_nested_url(value))
        for key, value in query
    ]
    return urlunsplit(
        (
            parts.scheme,
            netloc,
            parts.path,
            urlencode(redacted_query, safe="<>:/?="),
            parts.fragment,
        )
    )


def _redact_nested_url(value: str) -> str:
    if "?" not in value:
        return value
    nested = urlsplit(value)
    if not nested.scheme or not nested.netloc:
        return value
    return redact_url(value)


def _multipart_body(boundary: str, field_name: str, filename: str, data: bytes) -> bytes:
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        "Content-Type: application/x-nzb\r\n"
        "\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return header + data + footer


def _html_meta_charset(body: bytes) -> str | None:
    head = body[:4096].decode("ascii", errors="ignore")
    match = re.search(
        r"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9._-]+)""",
        head,
        re.IGNORECASE,
    )
    return match.group(1) if match else None
