from __future__ import annotations

import json
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
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}

    def get_text(self, url: str, timeout: float = 30) -> str:
        request = Request(url, headers=self.headers)
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset)

    def get_json(self, url: str, timeout: float = 30):
        return json.loads(self.get_text(url, timeout=timeout))


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
        (key, "<redacted>" if key.lower() in SECRET_QUERY_KEYS else value)
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
