from __future__ import annotations

from find_fel_nzbdav.webdav import (
    WebDavClient,
    basic_auth_header,
    find_largest_mkv,
    join_webdav_url,
)


PROPFIND = """<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/dav/content/job/small.mkv</D:href>
    <D:propstat><D:prop><D:getcontentlength>100</D:getcontentlength></D:prop></D:propstat>
  </D:response>
  <D:response>
    <D:href>/dav/content/job/movie.mkv</D:href>
    <D:propstat><D:prop><D:getcontentlength>1000</D:getcontentlength></D:prop></D:propstat>
  </D:response>
  <D:response>
    <D:href>/dav/content/job/movie.mp4</D:href>
    <D:propstat><D:prop><D:getcontentlength>9999</D:getcontentlength></D:prop></D:propstat>
  </D:response>
</D:multistatus>"""


def test_find_largest_mkv_ignores_non_mkv_files():
    calls = []

    class FakeHttp:
        def propfind(self, url, headers=None, timeout=10):
            calls.append((url, headers, timeout))
            return PROPFIND

    found = find_largest_mkv(FakeHttp(), "http://server:3000/dav", "/content/job/")

    assert found is not None
    assert found.path == "/dav/content/job/movie.mkv"
    assert found.size_bytes == 1000
    assert calls == [("http://server:3000/dav/content/job/", {}, 10)]


def test_find_largest_mkv_handles_percent_encoded_href_and_missing_lengths():
    propfind = """<?xml version="1.0"?>
    <multistatus xmlns="DAV:">
      <response>
        <href>/dav/content/job/Movie%20Name.mkv</href>
        <propstat><prop><getcontentlength>42</getcontentlength></prop></propstat>
      </response>
      <response>
        <href>/dav/content/job/unknown.mkv</href>
        <propstat><prop /></propstat>
      </response>
    </multistatus>"""

    class FakeHttp:
        def propfind(self, url, headers=None, timeout=10):
            return propfind

    found = find_largest_mkv(FakeHttp(), "http://server:3000/dav/", "content/job")

    assert found is not None
    assert found.path == "/dav/content/job/Movie%20Name.mkv"
    assert found.name == "Movie Name.mkv"
    assert found.size_bytes == 42


def test_find_largest_mkv_passes_basic_auth_header_when_configured():
    calls = []

    class FakeHttp:
        def propfind(self, url, headers=None, timeout=10):
            calls.append(headers)
            return PROPFIND

    found = find_largest_mkv(
        FakeHttp(),
        "http://server:3000/dav",
        "/content/job/",
        username="user",
        password="pass",
    )

    assert found is not None
    assert calls == [{"Authorization": "Basic dXNlcjpwYXNz"}]


def test_find_largest_mkv_returns_none_when_no_mkv_exists():
    propfind = """<?xml version="1.0"?>
    <D:multistatus xmlns:D="DAV:">
      <D:response>
        <D:href>/dav/content/job/movie.mp4</D:href>
        <D:propstat><D:prop><D:getcontentlength>9999</D:getcontentlength></D:prop></D:propstat>
      </D:response>
    </D:multistatus>"""

    class FakeHttp:
        def propfind(self, url, headers=None, timeout=10):
            return propfind

    assert find_largest_mkv(FakeHttp(), "http://server:3000/dav", "/content/job/") is None


def test_basic_auth_header_encodes_user_and_password():
    assert basic_auth_header("u", "p") == {"Authorization": "Basic dTpw"}


def test_webdav_client_propfind_uses_proper_method_headers_and_charset():
    calls = []

    class FakeHeaders:
        def get_content_charset(self):
            return "utf-8"

    class FakeResponse:
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b"<xml />"

    def opener(request, timeout=10):
        calls.append((request, timeout))
        return FakeResponse()

    client = WebDavClient(headers={"User-Agent": "find-fel"}, opener=opener)

    text = client.propfind(
        "http://server:3000/dav/content/job/",
        headers={"Authorization": "Basic token"},
        timeout=5,
    )

    request, timeout = calls[0]
    assert text == "<xml />"
    assert request.full_url == "http://server:3000/dav/content/job/"
    assert request.get_method() == "PROPFIND"
    assert request.get_header("Depth") == "infinity"
    assert request.get_header("Authorization") == "Basic token"
    assert request.get_header("User-agent") == "find-fel"
    assert timeout == 5


def test_join_webdav_url_handles_dav_href_without_doubling_dav():
    assert join_webdav_url("http://server:3000/dav", "/dav/content/job/movie.mkv") == (
        "http://server:3000/dav/content/job/movie.mkv"
    )


def test_join_webdav_url_handles_content_path_from_storage_conversion():
    assert join_webdav_url("http://server:3000", "/content/job/movie.mkv") == (
        "http://server:3000/content/job/movie.mkv"
    )


def test_join_webdav_url_handles_absolute_internal_href():
    assert join_webdav_url(
        "http://server:3000",
        "http://localhost:8080/content/job/movie.mkv",
    ) == "http://server:3000/content/job/movie.mkv"
