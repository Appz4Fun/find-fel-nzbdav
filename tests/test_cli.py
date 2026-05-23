from __future__ import annotations

import json
from pathlib import Path

from find_fel_nzbdav.cli import main, render_json
from find_fel_nzbdav.catalog import CatalogRelease
import find_fel_nzbdav.cli as cli_module
from find_fel_nzbdav.models import Candidate, CandidateResult, TitleResult


class FakeCatalogSource:
    def __init__(self, releases):
        self.releases = releases
        self.pages = []

    def discover_releases(self, pages=1):
        self.pages.append(pages)
        return self.releases


def _catalog_release(title: str, normalized_title: str, year: int) -> CatalogRelease:
    return CatalogRelease(
        source="bluray-com",
        source_id=normalized_title.replace(" ", "-"),
        source_url=f"https://www.blu-ray.com/movies/{normalized_title.replace(' ', '-')}/1/",
        title=title,
        normalized_title=normalized_title,
        year=year,
        country="United States",
        release_date=None,
        edition=None,
        studio=None,
        video="2160p",
        hdr="Dolby Vision",
        discs="4K Ultra HD",
        is_4k=True,
        is_dolby_vision=True,
    )


def test_catalog_json_uses_injected_source_without_env(capsys):
    fake_source = FakeCatalogSource(
        [
            _catalog_release("28 Days Later", "28 days later", 2002),
            _catalog_release("The Deer Hunter", "deer hunter", 1978),
        ]
    )

    exit_code = main(
        ["catalog", "--source", "bluray-com", "--json", "--pages", "1"],
        catalog_source=fake_source,
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert fake_source.pages == [1]
    assert output["source"] == "bluray-com"
    assert output["count"] == 2
    assert [row["title"] for row in output["titles"]] == [
        "28 Days Later",
        "The Deer Hunter",
    ]


def test_catalog_output_writes_json_file_and_prints_path(tmp_path: Path, capsys):
    output_path = tmp_path / "catalog.json"
    fake_source = FakeCatalogSource(
        [_catalog_release("The Deer Hunter", "deer hunter", 1978)]
    )

    exit_code = main(
        ["catalog", "--source", "bluray-com", "--output", str(output_path)],
        catalog_source=fake_source,
    )

    message = capsys.readouterr().out
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["source"] == "bluray-com"
    assert payload["count"] == 1
    assert payload["titles"][0]["title"] == "The Deer Hunter"
    assert str(output_path) in message


def test_catalog_json_zero_pages_returns_empty_payload(capsys):
    fake_source = FakeCatalogSource([])

    exit_code = main(
        ["catalog", "--source", "bluray-com", "--json", "--pages", "0"],
        catalog_source=fake_source,
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert fake_source.pages == [0]
    assert output == {
        "source": "bluray-com",
        "count": 0,
        "titles": [],
    }


def test_catalog_default_source_starts_http_with_project_user_agent(monkeypatch, capsys):
    captured = {}

    class FakeSource:
        def __init__(self, http, cache_dir, country, delay_seconds):
            captured["headers"] = dict(http.headers)
            captured["cache_dir"] = cache_dir
            captured["country"] = country
            captured["delay_seconds"] = delay_seconds

        def discover_releases(self, pages=1):
            captured["pages"] = pages
            return []

    monkeypatch.setattr(cli_module, "BlurayComSource", FakeSource)

    exit_code = main(["catalog", "--json", "--pages", "0"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["count"] == 0
    assert captured == {
        "headers": {"User-Agent": "find-fel-nzbdav/0.1"},
        "cache_dir": ".cache/bluray-com",
        "country": "all",
        "delay_seconds": 10.0,
        "pages": 0,
    }


def test_render_json_outputs_verdict_reason_and_candidates():
    candidate = Candidate("Release 2160p UHD DV", "http://nzb?apikey=secret", 123)
    result = TitleResult(
        title="Creepshow",
        verdict="unknown",
        reason="no_confirmed_fel",
        candidates=[
            CandidateResult(
                candidate=candidate,
                status="unknown",
                reason="profile_7_el_type_unknown",
                nzo_id="abc",
                webdav_path="/content/job/movie.mkv",
                stream_url_redacted="http://server/dav/content/job/movie.mkv",
                probe_summary="summary",
            )
        ],
    )

    payload = json.loads(render_json(result))

    assert payload["title"] == "Creepshow"
    assert payload["verdict"] == "unknown"
    assert payload["reason"] == "no_confirmed_fel"
    assert payload["candidates"][0]["release_title"] == "Release 2160p UHD DV"
    assert payload["candidates"][0]["link"] == "http://nzb?apikey=<redacted>"
    assert payload["candidates"][0]["status"] == "unknown"
    assert payload["candidates"][0]["probe_summary"] == "summary"


def test_main_json_returns_zero_for_not_fel_no_dv(tmp_path: Path, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "NZB_DAV_URL=http://server:3000\n"
        "NZB_DAV_API_KEY=nzbdav-secret\n"
        "HYDRA_URL=http://server:5076\n"
        "HYDRA_API_KEY=hydra-secret\n",
        encoding="utf-8",
    )

    class FakeHydra:
        def search(self, title):
            return []

    exit_code = main(
        ["--env", str(env_path), "--json", "Creepshow"],
        hydra=FakeHydra(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["verdict"] == "not_fel"
    assert output["reason"] == "no_dv_4k_candidates"


def test_main_returns_two_for_unknown_result(tmp_path: Path, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "NZB_DAV_URL=http://server:3000\n"
        "NZB_DAV_API_KEY=nzbdav-secret\n"
        "HYDRA_URL=http://server:5076\n"
        "HYDRA_API_KEY=hydra-secret\n",
        encoding="utf-8",
    )
    candidate = Candidate("Release 2160p UHD DV", "http://nzb", 10)

    class FakeHydra:
        def search(self, title):
            return [candidate]

    class FakeNZBDav:
        def submit_and_wait(self, candidate):
            raise RuntimeError("nope")

    exit_code = main(
        ["--env", str(env_path), "Title"],
        hydra=FakeHydra(),
        nzbdav=FakeNZBDav(),
        webdav=object(),
        probe=object(),
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "unknown" in output
