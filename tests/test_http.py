from find_fel_nzbdav.http import redact_url


def test_redact_url_hides_common_secret_parameters():
    redacted = redact_url("http://server/api?apikey=secret&name=http://x?a=1")

    assert "secret" not in redacted
    assert "apikey=<redacted>" in redacted


def test_redact_url_hides_nested_secret_parameters_inside_values():
    redacted = redact_url(
        "http://server/api?name=http%3A%2F%2Fhydra%2Fgetnzb%3Fapikey%3Dsecret&apikey=outer"
    )

    assert "secret" not in redacted
    assert "outer" not in redacted
    assert "apikey=<redacted>" in redacted


def test_http_client_posts_multipart_json():
    from find_fel_nzbdav.http import HttpClient

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
            return b'{"status":true}'

    def opener(request, timeout=30):
        calls.append((request, timeout))
        return FakeResponse()

    client = HttpClient(opener=opener)
    response = client.post_multipart_json(
        "http://server/api?mode=addfile",
        field_name="nzbfile",
        filename="movie.nzb",
        data=b"<nzb/>",
        timeout=12,
    )

    request, timeout = calls[0]
    body = request.data
    assert response == {"status": True}
    assert request.get_method() == "POST"
    assert request.get_header("Content-type").startswith("multipart/form-data; boundary=")
    assert b'name="nzbfile"; filename="movie.nzb"' in body
    assert b"<nzb/>" in body
    assert timeout == 12


def test_redact_url_hides_userinfo_password():
    redacted = redact_url("http://user:secret@server/path?apikey=abc")

    assert "secret" not in redacted
    assert "abc" not in redacted
    assert redacted == "http://<redacted>@server/path?apikey=<redacted>"
