from __future__ import annotations

import json
from pathlib import Path

from find_fel_nzbdav.cli import main, render_json
from find_fel_nzbdav.models import Candidate, CandidateResult, TitleResult


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
