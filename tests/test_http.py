from find_fel_nzbdav.http import redact_url


def test_redact_url_hides_common_secret_parameters():
    redacted = redact_url("http://server/api?apikey=secret&name=http://x?a=1")

    assert "secret" not in redacted
    assert "apikey=<redacted>" in redacted


def test_redact_url_hides_userinfo_password():
    redacted = redact_url("http://user:secret@server/path?apikey=abc")

    assert "secret" not in redacted
    assert "abc" not in redacted
    assert redacted == "http://<redacted>@server/path?apikey=<redacted>"
