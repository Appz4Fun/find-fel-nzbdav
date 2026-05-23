from find_fel_nzbdav.catalog import normalize_catalog_title
from find_fel_nzbdav.bluray_com import (
    BlurayComSource,
    build_search_url,
    parse_release_detail,
    parse_search_results,
)


def test_build_search_url_for_page_two_uses_expected_query():
    assert (
        build_search_url(page=2)
        == "https://www.blu-ray.com/movies/search.php?action=search&ultrahd=1&dolbyvision=1&sortby=releasetimestamp&page=2"
    )


def test_parse_search_results_returns_unique_constrained_detail_urls():
    html = """
    <a href="/movies/Blade-Runner-2049-4K-Blu-ray/189774/">movie</a>
    <a href="https://www.blu-ray.com/movies/Blade-Runner-2049-4K-Blu-ray/189774/">dupe</a>
    <a href="/movies/Arrival-Blu-ray/12345/">not 4k</a>
    <a href="/news/?id=999">news</a>
    <a href="https://example.com/movies/Fake-4K-Blu-ray/111/">external</a>
    <a href="/movies/Dune-4K-Blu-ray/292794/">second</a>
    """

    assert parse_search_results(html) == [
        "https://www.blu-ray.com/movies/Blade-Runner-2049-4K-Blu-ray/189774/",
        "https://www.blu-ray.com/movies/Dune-4K-Blu-ray/292794/",
    ]


def test_parse_release_detail_extracts_catalog_release_fields():
    url = "https://www.blu-ray.com/movies/Dune-Part-Two-4K-Blu-ray/355725/"
    html = """
    <html>
      <head>
        <meta property="og:title" content="Dune: Part Two 4K Blu-ray (United States)" />
      </head>
      <body>
        <h2>Video</h2>
        Codec: HEVC / H.265<br>
        Resolution: 2160p<br>
        HDR: HDR10 / Dolby Vision<br>
        <h2>Discs</h2>
        4K Ultra HD Blu-ray Disc<br>
        Two-disc set<br>
        <h2>Studio</h2>
        Warner Bros.<br>
        <h2>Release Date</h2>
        May 14, 2024<br>
        <h2>Edition</h2>
        SteelBook<br>
        <h2>Year</h2>
        2024<br>
        <p>This review prose should not matter.</p>
      </body>
    </html>
    """

    release = parse_release_detail(url, html)

    assert release.source == "bluray-com"
    assert release.source_id == "355725"
    assert release.source_url == url
    assert release.title == "Dune: Part Two"
    assert release.normalized_title == normalize_catalog_title("Dune: Part Two")
    assert release.year == 2024
    assert release.country == "United States"
    assert release.release_date == "May 14, 2024"
    assert release.edition == "SteelBook"
    assert release.studio == "Warner Bros."
    assert release.video == "Codec: HEVC / H.265\nResolution: 2160p\nHDR: HDR10 / Dolby Vision"
    assert release.hdr == "HDR10 / Dolby Vision"
    assert release.discs == "4K Ultra HD Blu-ray Disc\nTwo-disc set"
    assert release.is_4k is True
    assert release.is_dolby_vision is True
    assert release.fel_status == "unknown"


def test_parse_release_detail_supports_bluray_com_subheading_spans():
    release = parse_release_detail(
        "https://www.blu-ray.com/movies/28-Days-Later-4K-Blu-ray/410867/",
        """
        <meta property="og:title" content="28 Days Later 4K Blu-ray (United States)" />
        <span class="subheading">Video</span><br>
        Codec: HEVC / H.265<br>
        Resolution: 4K (2160p)<br>
        HDR: Dolby Vision, HDR10<br>
        <span class="subheading">Discs</span><br>
        4K Ultra HD<br>
        Blu-ray Disc<br>
        """,
    )

    assert release.video == (
        "Codec: HEVC / H.265\nResolution: 4K (2160p)\nHDR: Dolby Vision, HDR10"
    )
    assert release.discs == "4K Ultra HD\nBlu-ray Disc"
    assert release.is_4k is True
    assert release.is_dolby_vision is True


def test_parse_release_detail_classifies_hdr10_only_as_not_dolby_vision():
    release = parse_release_detail(
        "https://www.blu-ray.com/movies/Movie-4K-Blu-ray/1/",
        """
        <title>Movie 4K Blu-ray</title>
        <h2>Video</h2>
        Resolution: 2160p<br>
        HDR: HDR10<br>
        <h2>Discs</h2>
        4K Ultra HD Blu-ray<br>
        <p>The review mentions Dolby Vision in unrelated prose.</p>
        """,
    )

    assert release.hdr == "HDR10"
    assert release.is_dolby_vision is False


def test_parse_release_detail_classifies_non_4k_structured_data_as_not_4k():
    release = parse_release_detail(
        "https://www.blu-ray.com/movies/Movie-4K-Blu-ray/2/",
        """
        <title>Movie 4K Blu-ray</title>
        <h2>Video</h2>
        Resolution: 1080p<br>
        HDR: Dolby Vision<br>
        <h2>Disc</h2>
        Blu-ray Disc<br>
        """,
    )

    assert release.is_4k is False
    assert release.is_dolby_vision is True


def test_review_prose_does_not_override_structured_hdr10():
    release = parse_release_detail(
        "https://www.blu-ray.com/movies/Another-Movie-4K-Blu-ray/3/",
        """
        <meta property="og:title" content="Another Movie 4K Blu-ray" />
        <h2>Video</h2>
        Resolution: 2160p<br>
        HDR: HDR10<br>
        <p>Fans hoping for Dolby Vision will be disappointed.</p>
        """,
    )

    assert release.is_4k is True
    assert release.is_dolby_vision is False


def test_discover_releases_fetches_pages_and_filters_to_4k_dolby_vision():
    search_url = build_search_url(page=1)
    good_url = "https://www.blu-ray.com/movies/Good-Movie-4K-Blu-ray/10/"
    hdr10_url = "https://www.blu-ray.com/movies/HDR10-Movie-4K-Blu-ray/11/"
    non4k_url = "https://www.blu-ray.com/movies/HD-Movie-4K-Blu-ray/12/"
    responses = {
        search_url: f"""
            <a href="{good_url}">Good</a>
            <a href="{hdr10_url}">HDR10</a>
            <a href="{non4k_url}">HD</a>
        """,
        good_url: """
            <meta property="og:title" content="Good Movie 4K Blu-ray" />
            <h2>Video</h2>Resolution: 2160p<br>HDR: Dolby Vision<br>
            <h2>Discs</h2>4K Ultra HD Blu-ray<br>
        """,
        hdr10_url: """
            <meta property="og:title" content="HDR10 Movie 4K Blu-ray" />
            <h2>Video</h2>Resolution: 2160p<br>HDR: HDR10<br>
            <h2>Discs</h2>4K Ultra HD Blu-ray<br>
        """,
        non4k_url: """
            <meta property="og:title" content="HD Movie 4K Blu-ray" />
            <h2>Video</h2>Resolution: 1080p<br>HDR: Dolby Vision<br>
            <h2>Disc</h2>Blu-ray Disc<br>
        """,
    }
    http = FakeHttp(responses)

    releases = BlurayComSource(http=http, delay_seconds=0).discover_releases(pages=1)

    assert [release.source_id for release in releases] == ["10"]
    assert http.calls == [search_url, good_url, hdr10_url, non4k_url]


def test_discover_releases_supports_zero_pages():
    http = FakeHttp({})

    assert BlurayComSource(http=http, delay_seconds=0).discover_releases(pages=0) == []
    assert http.calls == []


def test_cache_reuses_text_response_for_same_url(tmp_path):
    url = "https://www.blu-ray.com/movies/Cached-Movie-4K-Blu-ray/20/"
    http = FakeHttp(
        {
            url: """
            <meta property="og:title" content="Cached Movie 4K Blu-ray" />
            <h2>Video</h2>Resolution: 2160p<br>HDR: Dolby Vision<br>
            <h2>Discs</h2>4K Ultra HD Blu-ray<br>
            """
        }
    )
    source = BlurayComSource(http=http, cache_dir=tmp_path, delay_seconds=0)

    assert source.fetch_text(url) == source.fetch_text(url)
    assert http.calls == [url]


class FakeHttp:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.headers = {}

    def get_text(self, url, timeout=30):
        self.calls.append(url)
        return self.responses[url]
