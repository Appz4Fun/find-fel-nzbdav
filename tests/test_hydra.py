from urllib.parse import parse_qs, urlsplit

import pytest

from hydra import (
    HydraError,
    filter_and_rank_candidates,
    has_4k_video_candidate,
    is_dv_4k_mkv_candidate,
    parse_hydra_results,
    search_hydra,
)


RSS = """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>Creepshow 1982 2160p UHD BluRay REMUX DV HEVC Atmos</title>
    <link>http://hydra/getnzb/one</link>
    <pubDate>Fri, 22 May 2026 20:15:00 +0000</pubDate>
    <newznab:attr xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/" name="size" value="9000" />
    <newznab:attr xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/" name="indexer" value="idx" />
  </item>
  <item>
    <title>Creepshow 1982 1080p BluRay</title>
    <link>http://hydra/getnzb/two</link>
    <newznab:attr xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/" name="size" value="999999" />
  </item>
  <item>
    <title>Creepshow 1982 2160p UHD BluRay REMUX HDR10 HEVC</title>
    <link>http://hydra/getnzb/three</link>
    <newznab:attr xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/" name="size" value="10000" />
  </item>
</channel></rss>"""


def test_parse_hydra_results_extracts_title_link_size_and_indexer():
    results = parse_hydra_results(RSS)

    assert results[0].release_title.startswith("Creepshow")
    assert results[0].link == "http://hydra/getnzb/one"
    assert results[0].size_bytes == 9000
    assert results[0].indexer == "idx"
    assert results[0].pubdate == "Fri, 22 May 2026 20:15:00 +0000"


def test_parse_hydra_results_extracts_newznab_attrs_without_namespace_prefix():
    rss = RSS.replace("newznab:attr", "attr").replace(
        ' xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/"',
        "",
    )

    results = parse_hydra_results(rss)

    assert results[0].size_bytes == 9000
    assert results[0].attributes["indexer"] == "idx"


def test_parse_hydra_results_rejects_newznab_error_response():
    xml = '<error code="900" description="Could not roll back JPA transaction" />'

    with pytest.raises(HydraError, match="Hydra error 900") as raised:
        parse_hydra_results(xml)
    assert raised.value.code == "900"


def test_filter_requires_dv_4k_and_mkv_likely_release():
    results = parse_hydra_results(RSS)

    ranked = filter_and_rank_candidates(results)

    assert [candidate.link for candidate in ranked] == ["http://hydra/getnzb/one"]


def test_detects_4k_video_candidates_without_requiring_dv():
    assert has_4k_video_candidate(
        [parse_hydra_results(RSS)[2]]
    )
    assert not has_4k_video_candidate(
        [parse_hydra_results(RSS)[1]]
    )


def test_filter_sorts_dv_4k_candidates_by_size_descending():
    results = parse_hydra_results(RSS.replace("HDR10", "DoVi").replace("10000", "10001"))

    ranked = filter_and_rank_candidates(results)

    assert [candidate.size_bytes for candidate in ranked] == [10001, 9000]


def test_filter_uses_standalone_dv_and_rejects_conservative_formats():
    assert is_dv_4k_mkv_candidate("Movie 2160p UHD BluRay DV REMUX HEVC")
    for rejected_format in ("MP4", "HDTV", "CAM", "TELESYNC"):
        assert not is_dv_4k_mkv_candidate(
            f"Movie 2160p UHD BluRay DV {rejected_format} HEVC"
        )
    assert not is_dv_4k_mkv_candidate("Movie 2160p UHD BluRay DVD REMUX HEVC")


def test_dv_4k_candidates_must_be_blu_ray_not_web_downloads():
    assert is_dv_4k_mkv_candidate("Movie 2160p UHD BluRay DV REMUX HEVC")
    assert is_dv_4k_mkv_candidate("Movie 2160p UHD Blu-ray DoVi HEVC")
    assert not is_dv_4k_mkv_candidate("Movie 2160p UHD WEB-DL DV HEVC")
    assert not is_dv_4k_mkv_candidate("Movie 2160p WEBRip DoVi HEVC")
    assert not is_dv_4k_mkv_candidate("Movie 2160p UHD DV HEVC")


def test_search_hydra_uses_movie_endpoint_movies_hd_and_min_size_window():
    calls = []

    class FakeHttp:
        def get_text(self, url, timeout=30):
            calls.append(url)
            return RSS

    found = search_hydra(FakeHttp(), "http://server:5076", "key", "Creepshow", limit=100)

    assert found.candidates[0].release_title.startswith("Creepshow")
    assert "q=Creepshow" in calls[0]
    params = parse_qs(urlsplit(calls[0]).query)
    assert params["t"] == ["movie"]
    assert params["cat"] == ["2040"]
    assert parse_qs(urlsplit(calls[0]).query)["o"] == ["xml"]
    assert params["minsize"] == ["3000"]
    assert "maxsize" not in params
    assert "apikey=key" in calls[0]
    assert "limit=100" in calls[0]
    assert found.raw_count == 3
    assert found.has_4k_video is True


def test_search_hydra_default_limit_does_not_cap_candidates_at_one_page():
    calls = []

    class FakeHttp:
        def get_text(self, url, timeout=30):
            calls.append(url)
            return RSS

    search_hydra(FakeHttp(), "http://server:5076", "key", "Creepshow")

    params = parse_qs(urlsplit(calls[0]).query)
    assert params["limit"] == ["10000"]


def test_search_hydra_normalizes_apostrophes_for_title_queries():
    calls = []

    class FakeHttp:
        def get_text(self, url, timeout=30):
            calls.append(url)
            return RSS

    search_hydra(FakeHttp(), "http://server:5076", "key", "Daddy's Home", limit=100)

    params = parse_qs(urlsplit(calls[0]).query)
    assert params["q"] == ["Daddys Home"]


def test_search_hydra_filters_out_sequel_and_collection_title_hits():
    rss = """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>Daddys.Home.2015.UHD.BluRay.2160p.DTS-X.7.1.DV.HEVC.REMUX-FraMeSToR</title>
    <link>http://hydra/getnzb/original</link>
    <newznab:attr xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/" name="size" value="60000000000" />
  </item>
  <item>
    <title>Daddys.Home.2.2017.2160p.UHD.BluRay.DV.HEVC.REMUX-FraMeSToR</title>
    <link>http://hydra/getnzb/sequel</link>
    <newznab:attr xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/" name="size" value="70000000000" />
  </item>
  <item>
    <title>The Daddys Home Collection 2015 2017 2160p UHD BluRay DV HEVC</title>
    <link>http://hydra/getnzb/collection</link>
    <newznab:attr xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/" name="size" value="80000000000" />
  </item>
</channel></rss>"""

    class FakeHttp:
        def get_text(self, url, timeout=30):
            return rss

    found = search_hydra(FakeHttp(), "http://server:5076", "key", "Daddy's Home")

    assert found.raw_count == 1
    assert [candidate.link for candidate in found.candidates] == [
        "http://hydra/getnzb/original"
    ]


def test_search_hydra_treats_only_sequel_hits_as_no_matching_results():
    rss = """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>Daddys.Home.2.2017.2160p.UHD.BluRay.DV.HEVC.REMUX-FraMeSToR</title>
    <link>http://hydra/getnzb/sequel</link>
    <newznab:attr xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/" name="size" value="70000000000" />
  </item>
</channel></rss>"""

    class FakeHttp:
        def get_text(self, url, timeout=30):
            return rss

    found = search_hydra(FakeHttp(), "http://server:5076", "key", "Daddy's Home")

    assert found.raw_count == 0
    assert found.has_4k_video is False
    assert found.candidates == []
