from __future__ import annotations

from find_fel_nzbdav.models import Candidate
from find_fel_nzbdav.probe import ProbeResult
from find_fel_nzbdav.workflow import check_title


def test_no_dv_candidates_auto_disqualifies_title():
    class FakeHydra:
        def search(self, title):
            return []

    result = check_title("Creepshow", hydra=FakeHydra(), nzbdav=None, webdav=None, probe=None)

    assert result.verdict == "not_fel"
    assert result.reason == "no_dv_4k_candidates"
    assert result.candidates == []


def test_stops_at_first_confirmed_fel_candidate():
    candidate = Candidate(
        release_title="Creepshow 2160p UHD REMUX DV",
        link="http://nzb/one",
        size_bytes=10,
    )

    class FakeHydra:
        def search(self, title):
            return [candidate]

    class FakeNZBDav:
        def submit_and_wait(self, candidate):
            return type("Completed", (), {"nzo_id": "abc", "storage": "/content/job/"})()

    class FakeWebDAV:
        def find_mkv(self, storage):
            return type(
                "Mkv",
                (),
                {
                    "path": "/content/job/movie.mkv",
                    "url": "http://stream/movie.mkv",
                    "headers": {},
                },
            )()

    class FakeProbe:
        def probe(self, url, headers):
            return ProbeResult(verdict="fel", reason="profile_7_fel", summary="ok")

    result = check_title("Creepshow", FakeHydra(), FakeNZBDav(), FakeWebDAV(), FakeProbe())

    assert result.verdict == "fel"
    assert result.reason == "profile_7_fel"
    assert result.candidates[0].status == "fel"
    assert result.candidates[0].nzo_id == "abc"
    assert result.candidates[0].webdav_path == "/content/job/movie.mkv"
    assert result.candidates[0].stream_url_redacted == "http://stream/movie.mkv"


def test_continues_after_submit_failure_to_next_candidate():
    first = Candidate("bad release 2160p UHD DV", "http://nzb/bad", 20)
    second = Candidate("good release 2160p UHD DV", "http://nzb/good", 10)
    submitted = []

    class FakeHydra:
        def search(self, title):
            return [first, second]

    class FakeNZBDav:
        def submit_and_wait(self, candidate):
            submitted.append(candidate.link)
            if candidate is first:
                raise RuntimeError("submit boom")
            return type("Completed", (), {"nzo_id": "good-id", "storage": "/content/job/"})()

    class FakeWebDAV:
        def find_mkv(self, storage):
            return type(
                "Mkv",
                (),
                {"path": "/content/job/movie.mkv", "url": "http://stream", "headers": {}},
            )()

    class FakeProbe:
        def probe(self, url, headers):
            return ProbeResult("fel", "profile_7_fel", "ok")

    result = check_title("Title", FakeHydra(), FakeNZBDav(), FakeWebDAV(), FakeProbe())

    assert result.verdict == "fel"
    assert submitted == ["http://nzb/bad", "http://nzb/good"]
    assert result.candidates[0].status == "error"
    assert result.candidates[0].reason == "submit_failed"
    assert result.candidates[1].status == "fel"


def test_all_unknown_candidates_returns_unknown():
    candidate = Candidate("release 2160p UHD DV", "http://nzb/one", 10)

    class FakeHydra:
        def search(self, title):
            return [candidate]

    class FakeNZBDav:
        def submit_and_wait(self, candidate):
            return type("Completed", (), {"nzo_id": "abc", "storage": "/content/job/"})()

    class FakeWebDAV:
        def find_mkv(self, storage):
            return type(
                "Mkv",
                (),
                {"path": "/content/job/movie.mkv", "url": "http://stream", "headers": {}},
            )()

    class FakeProbe:
        def probe(self, url, headers):
            return ProbeResult("unknown", "profile_7_el_type_unknown", "summary")

    result = check_title("Title", FakeHydra(), FakeNZBDav(), FakeWebDAV(), FakeProbe())

    assert result.verdict == "unknown"
    assert result.reason == "no_confirmed_fel"
    assert result.candidates[0].status == "unknown"
    assert result.candidates[0].probe_summary == "summary"


def test_deduplicates_candidates_before_submitting_top_three():
    duplicate_a = Candidate("same 2160p UHD DV", "http://nzb/a", 10)
    duplicate_b = Candidate("same 2160p UHD DV", "http://nzb/b", 10)
    unique = Candidate("unique 2160p UHD DV", "http://nzb/c", 9)
    submitted = []

    class FakeHydra:
        def search(self, title):
            return [duplicate_a, duplicate_b, unique]

    class FakeNZBDav:
        def submit_and_wait(self, candidate):
            submitted.append(candidate.link)
            raise RuntimeError("stop")

    result = check_title(
        "Title",
        FakeHydra(),
        FakeNZBDav(),
        webdav=None,
        probe=None,
        max_candidates=3,
    )

    assert result.verdict == "unknown"
    assert submitted == ["http://nzb/a", "http://nzb/c"]
