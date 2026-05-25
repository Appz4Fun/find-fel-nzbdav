from __future__ import annotations

from hydra import HydraError, HydraSearchResult
from models import Candidate
from probe import ProbeResult
from workflow import check_title, check_title_with_retries


def test_no_raw_hydra_results_stays_unknown_for_future_retry():
    class FakeHydra:
        def search(self, title):
            return HydraSearchResult(raw_candidates=[], candidates=[])

    result = check_title("Creepshow", hydra=FakeHydra(), nzbdav=None, webdav=None, probe=None)

    assert result.verdict == "unknown"
    assert result.reason == "no_hydra_results"
    assert result.candidates == []


def test_raw_hydra_results_without_4k_video_auto_disqualify_title():
    class FakeHydra:
        def search(self, title):
            return HydraSearchResult(
                raw_candidates=[Candidate("Creepshow 1982 1080p BluRay", "http://nzb/one", 10)],
                candidates=[],
            )

    result = check_title("Creepshow", hydra=FakeHydra(), nzbdav=None, webdav=None, probe=None)

    assert result.verdict == "not_fel"
    assert result.reason == "no_4k_video_candidates"
    assert result.candidates == []


def test_4k_hydra_results_without_dv_auto_disqualify_title():
    class FakeHydra:
        def search(self, title):
            return HydraSearchResult(
                raw_candidates=[
                    Candidate(
                        "Creepshow 1982 2160p UHD BluRay REMUX HDR10 HEVC",
                        "http://nzb/one",
                        10,
                    )
                ],
                candidates=[],
            )

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


def test_article_health_submit_failure_is_labeled_and_continues():
    first = Candidate("bad release 2160p UHD BluRay DV", "http://nzb/bad", 20)
    second = Candidate("good release 2160p UHD BluRay DV", "http://nzb/good", 10)

    class FakeHydra:
        def search(self, title):
            return [first, second]

    class FakeNZBDav:
        def submit_and_wait(self, candidate):
            if candidate is first:
                raise RuntimeError("Article with message-id abc not found.")
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
    assert result.candidates[0].reason == "article_health_failed"
    assert result.candidates[1].status == "fel"


def test_default_candidate_loop_has_no_three_release_cap():
    candidates = [
        Candidate(f"bad release {index} 2160p UHD BluRay DV", f"http://nzb/bad-{index}", 20 - index)
        for index in range(3)
    ]
    winner = Candidate("good release 2160p UHD BluRay DV", "http://nzb/good", 10)
    submitted = []

    class FakeHydra:
        def search(self, title):
            return candidates + [winner]

    class FakeNZBDav:
        def submit_and_wait(self, candidate):
            submitted.append(candidate.link)
            if candidate is winner:
                return type("Completed", (), {"nzo_id": "good-id", "storage": "/content/job/"})()
            raise RuntimeError("article health failure")

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
    assert submitted == [
        "http://nzb/bad-0",
        "http://nzb/bad-1",
        "http://nzb/bad-2",
        "http://nzb/good",
    ]


def test_all_unknown_dv_candidates_returns_profile_undetected():
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
    assert result.reason == "dv_4k_profile_undetected"
    assert result.candidates[0].status == "unknown"
    assert result.candidates[0].probe_summary == "summary"


def test_unknown_profile_continues_to_later_valid_dv_profile():
    first = Candidate("unknown release 2160p UHD BluRay DV", "http://nzb/unknown", 20)
    second = Candidate("mel release 2160p UHD BluRay DV", "http://nzb/mel", 10)
    submitted = []

    class FakeHydra:
        def search(self, title):
            return [first, second]

    class FakeNZBDav:
        def submit_and_wait(self, candidate):
            submitted.append(candidate.link)
            return type("Completed", (), {"nzo_id": candidate.link.rsplit("/", 1)[-1], "storage": "/content/job/"})()

    class FakeWebDAV:
        def find_mkv(self, storage):
            return type(
                "Mkv",
                (),
                {"path": "/content/job/movie.mkv", "url": "http://stream", "headers": {}},
            )()

    class FakeProbe:
        def probe(self, url, headers):
            if len(submitted) == 1:
                return ProbeResult("unknown", "dolby_vision_profile_unknown", "summary")
            return ProbeResult("not_fel", "profile_7_mel", "summary")

    result = check_title("Title", FakeHydra(), FakeNZBDav(), FakeWebDAV(), FakeProbe())

    assert result.verdict == "not_fel"
    assert result.reason == "profile_7_mel"
    assert submitted == ["http://nzb/unknown", "http://nzb/mel"]


def test_detected_non_fel_profile_is_not_fel_even_if_another_candidate_errors():
    first = Candidate("mel release 2160p UHD DV", "http://nzb/mel", 20)
    second = Candidate("bad release 2160p UHD DV", "http://nzb/bad", 10)

    class FakeHydra:
        def search(self, title):
            return [first, second]

    class FakeNZBDav:
        def submit_and_wait(self, candidate):
            if candidate is second:
                raise RuntimeError("submit boom")
            return type("Completed", (), {"nzo_id": "mel-id", "storage": "/content/job/"})()

    class FakeWebDAV:
        def find_mkv(self, storage):
            return type(
                "Mkv",
                (),
                {"path": "/content/job/movie.mkv", "url": "http://stream", "headers": {}},
            )()

    class FakeProbe:
        def probe(self, url, headers):
            return ProbeResult("not_fel", "profile_7_mel", "summary")

    result = check_title("Title", FakeHydra(), FakeNZBDav(), FakeWebDAV(), FakeProbe())

    assert result.verdict == "not_fel"
    assert result.reason == "profile_7_mel"


def test_stops_at_first_valid_non_fel_dv_profile():
    first = Candidate("mel release 2160p UHD BluRay DV", "http://nzb/mel", 20)
    second = Candidate("should not submit 2160p UHD BluRay DV", "http://nzb/later", 10)
    submitted = []

    class FakeHydra:
        def search(self, title):
            return [first, second]

    class FakeNZBDav:
        def submit_and_wait(self, candidate):
            submitted.append(candidate.link)
            if candidate is second:
                raise AssertionError("valid profile should stop this title")
            return type("Completed", (), {"nzo_id": "mel-id", "storage": "/content/job/"})()

    class FakeWebDAV:
        def find_mkv(self, storage):
            return type(
                "Mkv",
                (),
                {"path": "/content/job/movie.mkv", "url": "http://stream", "headers": {}},
            )()

    class FakeProbe:
        def probe(self, url, headers):
            return ProbeResult("not_fel", "profile_7_mel", "summary")

    result = check_title("Title", FakeHydra(), FakeNZBDav(), FakeWebDAV(), FakeProbe())

    assert result.verdict == "not_fel"
    assert result.reason == "profile_7_mel"
    assert submitted == ["http://nzb/mel"]


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


def test_hydra_error_reason_preserves_error_code_after_retries():
    class BrokenHydra:
        def search(self, title):
            raise HydraError("900", "Could not roll back JPA transaction")

    result, failed = check_title_with_retries(
        "Title",
        BrokenHydra(),
        nzbdav=object(),
        webdav=object(),
        probe=object(),
        max_candidates=3,
        retries=0,
        retry_wait=0.0,
    )

    assert failed is True
    assert result.verdict == "unknown"
    assert result.reason == "error_Hydra_900"
