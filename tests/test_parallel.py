from __future__ import annotations

import threading
from dataclasses import dataclass

from config import NZBDavEndpoint
from hydra import HydraSearchResult
from models import Candidate, TitleResult
import parallel


@dataclass
class _RecordingHydra:
    """Fake hydra that records (title, endpoint_url_seen) and returns no candidates."""
    seen: list[tuple[str, str]]
    lock: threading.Lock

    def make_call(self, endpoint_url: str):
        def search(title: str):
            with self.lock:
                self.seen.append((title, endpoint_url))
            return _no_dv_4k_hydra_result()
        return search


class _StaticHydra:
    """Simpler hydra: always returns empty so workers report not_fel quickly."""
    def search(self, title: str):
        return _no_dv_4k_hydra_result()


def _no_dv_4k_hydra_result() -> HydraSearchResult:
    candidate = Candidate("Movie 2160p UHD BluRay REMUX HDR10 HEVC", "http://nzb/one", 10)
    return HydraSearchResult(raw_candidates=[candidate], candidates=[])


def test_run_parallel_processes_all_titles_across_endpoints():
    endpoints = [
        NZBDavEndpoint(url="http://dav1", api_key="A", webdav_url="http://dav1"),
        NZBDavEndpoint(url="http://dav2", api_key="B", webdav_url="http://dav2"),
        NZBDavEndpoint(url="http://dav3", api_key="C", webdav_url="http://dav3"),
    ]
    titles = ["t1", "t2", "t3", "t4", "t5", "t6"]
    results: list[tuple[str, TitleResult, bool]] = []
    results_lock = threading.Lock()

    def on_result(title, result, failed):
        with results_lock:
            results.append((title, result, failed))

    parallel.run_parallel(
        titles,
        endpoints,
        hydra=_StaticHydra(),
        probe=object(),
        max_candidates=3,
        poll_interval=0.0,
        nzbdav_timeout=1.0,
        retries=0,
        retry_wait=0.0,
        on_result=on_result,
    )

    assert {title for title, _, _ in results} == set(titles)
    assert len(results) == len(titles)
    for _, result, failed in results:
        assert result.verdict == "not_fel"
        assert result.reason == "no_dv_4k_candidates"
        assert failed is False


def test_run_parallel_empty_title_list_returns_immediately():
    endpoints = [
        NZBDavEndpoint(url="http://dav1", api_key="A", webdav_url="http://dav1"),
        NZBDavEndpoint(url="http://dav2", api_key="B", webdav_url="http://dav2"),
    ]
    on_result_called: list[object] = []

    parallel.run_parallel(
        [],
        endpoints,
        hydra=_StaticHydra(),
        probe=object(),
        max_candidates=3,
        poll_interval=0.0,
        nzbdav_timeout=1.0,
        retries=0,
        retry_wait=0.0,
        on_result=lambda *a, **kw: on_result_called.append(a),
    )

    assert on_result_called == []


def test_run_parallel_marks_failed_titles_when_hydra_raises():
    class BrokenHydra:
        def search(self, title):
            raise RuntimeError(f"hydra broken on {title}")

    endpoints = [
        NZBDavEndpoint(url="http://dav1", api_key="A", webdav_url="http://dav1"),
        NZBDavEndpoint(url="http://dav2", api_key="B", webdav_url="http://dav2"),
    ]
    titles = ["a", "b", "c", "d"]
    results: list[tuple[str, TitleResult, bool]] = []
    results_lock = threading.Lock()

    def on_result(title, result, failed):
        with results_lock:
            results.append((title, result, failed))

    parallel.run_parallel(
        titles,
        endpoints,
        hydra=BrokenHydra(),
        probe=object(),
        max_candidates=3,
        poll_interval=0.0,
        nzbdav_timeout=1.0,
        retries=0,
        retry_wait=0.0,
        on_result=on_result,
    )

    assert {title for title, _, _ in results} == set(titles)
    for _, result, failed in results:
        assert failed is True
        assert result.verdict == "unknown"
        assert result.reason == "error_RuntimeError"


def test_run_parallel_aborts_after_consecutive_infrastructure_failures():
    class BrokenHydra:
        def search(self, title):
            raise RuntimeError(f"hydra broken on {title}")

    endpoints = [
        NZBDavEndpoint(url="http://dav1", api_key="A", webdav_url="http://dav1"),
    ]
    titles = ["a", "b", "c", "d"]
    results: list[tuple[str, TitleResult, bool]] = []

    summary = parallel.run_parallel(
        titles,
        endpoints,
        hydra=BrokenHydra(),
        probe=object(),
        max_candidates=3,
        poll_interval=0.0,
        nzbdav_timeout=1.0,
        retries=0,
        retry_wait=0.0,
        max_consecutive_failures=2,
        on_result=lambda title, result, failed: results.append((title, result, failed)),
    )

    assert summary.aborted is True
    assert summary.processed == 2
    assert summary.unprocessed == 2
    assert [title for title, _, _ in results] == ["a", "b"]


def test_run_parallel_workers_use_their_assigned_endpoint():
    """One worker per endpoint; each worker's NZBDavAdapter is built from its own endpoint."""
    seen_endpoint_urls: list[str] = []
    seen_lock = threading.Lock()

    class _SpyHydra:
        def __init__(self, recorder, lock):
            self.recorder = recorder
            self.lock = lock
        def search(self, title):
            # Hydra is shared, so we can't see which worker called us by hydra alone.
            # Instead, the test below uses a spy on parallel._build_adapters.
            return []

    endpoints = [
        NZBDavEndpoint(url="http://dav-A", api_key="A", webdav_url="http://dav-A"),
        NZBDavEndpoint(url="http://dav-B", api_key="B", webdav_url="http://dav-B"),
    ]

    # Monkey-patch _build_adapters to record which endpoint each worker used.
    original = parallel._build_adapters
    try:
        def spy(endpoint, poll_interval, timeout):
            with seen_lock:
                seen_endpoint_urls.append(endpoint.url)
            return original(endpoint, poll_interval, timeout)
        parallel._build_adapters = spy

        parallel.run_parallel(
            ["t1", "t2", "t3"],
            endpoints,
            hydra=_StaticHydra(),
            probe=object(),
            max_candidates=3,
            poll_interval=0.0,
            nzbdav_timeout=1.0,
            retries=0,
            retry_wait=0.0,
            on_result=lambda *a, **kw: None,
        )
    finally:
        parallel._build_adapters = original

    assert sorted(seen_endpoint_urls) == ["http://dav-A", "http://dav-B"]
