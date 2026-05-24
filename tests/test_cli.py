from __future__ import annotations

import datetime
import json
from pathlib import Path

from catalog import CatalogRelease
from cli import (
    default_log_path,
    format_log_line,
    main,
    parse_titles_file,
    render_json,
)
import cli as cli_module
from models import Candidate, CandidateResult, TitleResult


ENV_TEXT = (
    "NZB_DAV_URL=http://server:3000\n"
    "NZB_DAV_API_KEY=nzbdav-secret\n"
    "HYDRA_URL=http://server:5076\n"
    "HYDRA_API_KEY=hydra-secret\n"
)


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
        ["--env", str(env_path), "--no-db", "--json", "Creepshow"],
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
        ["--env", str(env_path), "--no-db", "Title"],
        hydra=FakeHydra(),
        nzbdav=FakeNZBDav(),
        webdav=object(),
        probe=object(),
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "unknown" in output


def test_parse_titles_file_strips_blank_lines_and_comments_and_preserves_order(
    tmp_path: Path,
):
    titles_path = tmp_path / "titles.txt"
    titles_path.write_text(
        "# leading comment\n"
        "Creepshow\n"
        "\n"
        "  The Deer Hunter  \n"
        "# Despicable Me 4\n"
        "Despicable Me 4\n"
        "Creepshow\n",
        encoding="utf-8",
    )

    assert parse_titles_file(titles_path) == [
        "Creepshow",
        "The Deer Hunter",
        "Despicable Me 4",
        "Creepshow",
    ]


def test_main_rejects_when_both_title_and_titles_file_provided(tmp_path: Path, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text(ENV_TEXT, encoding="utf-8")
    titles_path = tmp_path / "titles.txt"
    titles_path.write_text("Creepshow\n", encoding="utf-8")

    exit_code = main(
        ["--env", str(env_path), "--no-db", "--titles-file", str(titles_path), "Creepshow"],
        hydra=object(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
    )

    assert exit_code == 2
    assert "exactly one" in capsys.readouterr().err


def test_main_rejects_when_neither_title_nor_titles_file_provided(tmp_path: Path, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text(ENV_TEXT, encoding="utf-8")

    exit_code = main(
        ["--env", str(env_path)],
        hydra=object(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
    )

    assert exit_code == 2
    assert "exactly one" in capsys.readouterr().err


def test_main_titles_file_emits_one_json_line_per_title(tmp_path: Path, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text(ENV_TEXT, encoding="utf-8")
    titles_path = tmp_path / "titles.txt"
    titles_path.write_text("Creepshow\nThe Deer Hunter\n", encoding="utf-8")

    class FakeHydra:
        def search(self, title):
            return []

    exit_code = main(
        ["--env", str(env_path), "--no-db", "--json", "--titles-file", str(titles_path)],
        hydra=FakeHydra(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
    )

    stdout = capsys.readouterr().out
    lines = [line for line in stdout.splitlines() if line]
    payloads = [json.loads(line) for line in lines]

    assert exit_code == 0
    assert [payload["title"] for payload in payloads] == ["Creepshow", "The Deer Hunter"]
    assert all(payload["verdict"] == "not_fel" for payload in payloads)
    assert all(payload["reason"] == "no_dv_4k_candidates" for payload in payloads)


def test_main_titles_file_continues_after_per_title_exception(tmp_path: Path, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text(ENV_TEXT, encoding="utf-8")
    titles_path = tmp_path / "titles.txt"
    titles_path.write_text("Boom\nCreepshow\n", encoding="utf-8")

    class FakeHydra:
        def search(self, title):
            if title == "Boom":
                raise RuntimeError("hydra outage")
            return []

    exit_code = main(
        ["--env", str(env_path), "--no-db", "--json", "--titles-file", str(titles_path)],
        hydra=FakeHydra(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
    )

    payloads = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line
    ]

    assert exit_code == 0
    assert [payload["title"] for payload in payloads] == ["Boom", "Creepshow"]
    assert payloads[0]["verdict"] == "unknown"
    assert payloads[0]["reason"] == "error_RuntimeError"
    assert payloads[1]["verdict"] == "not_fel"


def test_main_titles_file_returns_two_when_every_title_is_indeterminate(
    tmp_path: Path, capsys
):
    env_path = tmp_path / ".env"
    env_path.write_text(ENV_TEXT, encoding="utf-8")
    titles_path = tmp_path / "titles.txt"
    titles_path.write_text("Boom\n", encoding="utf-8")

    class FakeHydra:
        def search(self, title):
            raise RuntimeError("hydra outage")

    exit_code = main(
        ["--env", str(env_path), "--no-db", "--json", "--titles-file", str(titles_path)],
        hydra=FakeHydra(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
    )

    assert exit_code == 2
    payloads = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    assert payloads[0]["verdict"] == "unknown"


def test_default_log_path_combines_logs_dir_with_timestamp():
    now = datetime.datetime(2026, 5, 22, 23, 45, 12)

    assert default_log_path(now) == Path("logs") / "find-fel-20260522-234512.log"


def test_format_log_line_includes_iso_timestamp_title_verdict_and_reason():
    result = TitleResult.not_fel("Creepshow", "no_dv_4k_candidates")
    now = datetime.datetime(2026, 5, 22, 23, 45, 12)

    assert (
        format_log_line(result, now)
        == "[2026-05-22T23:45:12] Creepshow: not_fel (no_dv_4k_candidates)"
    )


def test_main_writes_one_log_line_per_title_to_explicit_log_file(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(ENV_TEXT, encoding="utf-8")
    titles_path = tmp_path / "titles.txt"
    titles_path.write_text("Creepshow\nDespicable Me 4\n", encoding="utf-8")
    log_path = tmp_path / "out.log"

    class FakeHydra:
        def search(self, title):
            return []

    main(
        [
            "--env", str(env_path), "--no-db",
            "--titles-file", str(titles_path),
            "--log-file", str(log_path),
        ],
        hydra=FakeHydra(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
    )

    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line]

    assert len(lines) == 2
    assert lines[0].endswith("Creepshow: not_fel (no_dv_4k_candidates)")
    assert lines[1].endswith("Despicable Me 4: not_fel (no_dv_4k_candidates)")


def test_main_creates_log_parent_directory_when_missing(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(ENV_TEXT, encoding="utf-8")
    log_path = tmp_path / "nested" / "deep" / "out.log"

    class FakeHydra:
        def search(self, title):
            return []

    main(
        [
            "--env", str(env_path), "--no-db",
            "--log-file", str(log_path),
            "Creepshow",
        ],
        hydra=FakeHydra(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
    )

    assert log_path.exists()
    assert "Creepshow" in log_path.read_text(encoding="utf-8")


def test_main_logs_error_verdicts_for_per_title_exceptions(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(ENV_TEXT, encoding="utf-8")
    titles_path = tmp_path / "titles.txt"
    titles_path.write_text("Boom\nOk\n", encoding="utf-8")
    log_path = tmp_path / "out.log"

    class FakeHydra:
        def search(self, title):
            if title == "Boom":
                raise RuntimeError("hydra outage")
            return []

    main(
        [
            "--env", str(env_path), "--no-db",
            "--titles-file", str(titles_path),
            "--log-file", str(log_path),
        ],
        hydra=FakeHydra(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
    )

    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line]

    assert lines[0].endswith("Boom: unknown (error_RuntimeError)")
    assert lines[1].endswith("Ok: not_fel (no_dv_4k_candidates)")


import sqlite3


def test_main_single_title_upserts_result_to_db(tmp_path: Path, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text(ENV_TEXT, encoding="utf-8")
    db_path = tmp_path / "find-fel.db"
    log_path = tmp_path / "run.log"

    class FakeHydra:
        def search(self, title):
            return []

    exit_code = main(
        [
            "--env", str(env_path),
            "--db", str(db_path),
            "--log-file", str(log_path),
            "--json",
            "Creepshow",
        ],
        hydra=FakeHydra(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
    )

    assert exit_code == 0
    capsys.readouterr()  # drain
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT title, verdict, reason FROM titles"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("Creepshow", "not_fel", "no_dv_4k_candidates")


def test_main_titles_file_upserts_each_title_to_db(tmp_path: Path, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text(ENV_TEXT, encoding="utf-8")
    titles_path = tmp_path / "titles.txt"
    titles_path.write_text("Creepshow\nThe Deer Hunter\n", encoding="utf-8")
    db_path = tmp_path / "find-fel.db"
    log_path = tmp_path / "run.log"

    class FakeHydra:
        def search(self, title):
            return []

    exit_code = main(
        [
            "--env", str(env_path),
            "--db", str(db_path),
            "--log-file", str(log_path),
            "--json",
            "--titles-file", str(titles_path),
        ],
        hydra=FakeHydra(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
    )

    assert exit_code == 0
    capsys.readouterr()
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT title, verdict, reason FROM titles ORDER BY title"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [
        ("Creepshow", "not_fel", "no_dv_4k_candidates"),
        ("The Deer Hunter", "not_fel", "no_dv_4k_candidates"),
    ]


def test_main_no_db_flag_disables_db_writes(tmp_path: Path, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text(ENV_TEXT, encoding="utf-8")
    db_path = tmp_path / "find-fel.db"
    log_path = tmp_path / "run.log"

    class FakeHydra:
        def search(self, title):
            return []

    exit_code = main(
        [
            "--env", str(env_path),
            "--db", str(db_path),
            "--no-db",
            "--log-file", str(log_path),
            "--json",
            "Creepshow",
        ],
        hydra=FakeHydra(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
    )

    capsys.readouterr()
    assert exit_code == 0
    assert not db_path.exists()
