from urllib.parse import parse_qs, urlsplit

from hydra import (
    filter_and_rank_candidates,
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


def test_filter_requires_dv_4k_and_mkv_likely_release():
    results = parse_hydra_results(RSS)

    ranked = filter_and_rank_candidates(results)

    assert [candidate.link for candidate in ranked] == ["http://hydra/getnzb/one"]


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


def test_search_hydra_uses_newznab_search_endpoint():
    calls = []

    class FakeHttp:
        def get_text(self, url, timeout=30):
            calls.append(url)
            return RSS

    found = search_hydra(FakeHttp(), "http://server:5076", "key", "Creepshow", limit=100)

    assert found[0].release_title.startswith("Creepshow")
    assert "t=search" in calls[0]
    assert "q=Creepshow" in calls[0]
    assert parse_qs(urlsplit(calls[0]).query)["o"] == ["xml"]
    assert "apikey=key" in calls[0]
    assert "limit=100" in calls[0]
