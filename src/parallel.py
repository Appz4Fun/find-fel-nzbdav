from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from config import NZBDavEndpoint
from httpclient import HttpClient
from models import TitleResult
from nzbdav import NZBDavClient
from webdav import WebDavClient
from workflow import check_title_with_retries


# Sentinel object placed on the work queue to signal worker shutdown.
_SHUTDOWN = object()


@dataclass(frozen=True)
class ParallelRunSummary:
    processed: int
    unprocessed: int
    aborted: bool


def run_parallel(
    titles: Iterable[str],
    endpoints: list[NZBDavEndpoint],
    *,
    hydra,
    probe,
    max_candidates: int | None,
    poll_interval: float,
    nzbdav_timeout: float,
    retries: int,
    retry_wait: float,
    max_consecutive_failures: int | None = None,
    on_result: Callable[[str, TitleResult, bool], None],
) -> ParallelRunSummary:
    if not endpoints:
        raise ValueError("run_parallel requires at least one endpoint")

    titles_list = list(titles)
    if not titles_list:
        return ParallelRunSummary(processed=0, unprocessed=0, aborted=False)

    work_q: queue.Queue = queue.Queue()
    result_q: queue.Queue = queue.Queue()
    stop_event = threading.Event()

    threads = [
        threading.Thread(
            target=_worker_loop,
            args=(
                endpoint,
                work_q,
                result_q,
                hydra,
                probe,
                max_candidates,
                poll_interval,
                nzbdav_timeout,
                retries,
                retry_wait,
                stop_event,
            ),
            daemon=False,
            name=f"find-fel-worker-{index}",
        )
        for index, endpoint in enumerate(endpoints)
    ]
    for thread in threads:
        thread.start()

    next_title_index = 0
    in_flight = 0

    def dispatch_next() -> None:
        nonlocal next_title_index, in_flight
        if next_title_index >= len(titles_list) or stop_event.is_set():
            return
        work_q.put(titles_list[next_title_index])
        next_title_index += 1
        in_flight += 1

    for _ in range(min(len(endpoints), len(titles_list))):
        dispatch_next()

    processed = 0
    consecutive_failures = 0
    aborted = False
    while in_flight > 0:
        try:
            title, result, failed = result_q.get(timeout=0.1)
        except queue.Empty:
            if not any(thread.is_alive() for thread in threads):
                break
            continue

        processed += 1
        in_flight -= 1
        on_result(title, result, failed)
        if failed:
            consecutive_failures += 1
            if (
                max_consecutive_failures is not None
                and max_consecutive_failures > 0
                and consecutive_failures >= max_consecutive_failures
            ):
                aborted = True
                stop_event.set()
        else:
            consecutive_failures = 0

        if not aborted:
            dispatch_next()

    for _ in endpoints:
        work_q.put(_SHUTDOWN)

    for thread in threads:
        thread.join()
    return ParallelRunSummary(
        processed=processed,
        unprocessed=len(titles_list) - processed,
        aborted=aborted,
    )


def _worker_loop(
    endpoint: NZBDavEndpoint,
    work_q: queue.Queue,
    result_q: queue.Queue,
    hydra,
    probe,
    max_candidates: int | None,
    poll_interval: float,
    nzbdav_timeout: float,
    retries: int,
    retry_wait: float,
    stop_event: threading.Event,
) -> None:
    nzbdav, webdav = _build_adapters(endpoint, poll_interval, nzbdav_timeout)

    while True:
        if stop_event.is_set():
            return
        item = work_q.get()
        if item is _SHUTDOWN:
            return
        if stop_event.is_set():
            return
        title: str = item
        result, failed = check_title_with_retries(
            title,
            hydra,
            nzbdav,
            webdav,
            probe,
            max_candidates=max_candidates,
            retries=retries,
            retry_wait=retry_wait,
        )
        result_q.put((title, result, failed))


def _build_adapters(endpoint: NZBDavEndpoint, poll_interval: float, timeout: float):
    """Build per-worker NZBDavAdapter and WebDavAdapter from an endpoint.

    Returns (nzbdav_adapter, webdav_adapter). Import the adapter classes lazily
    from cli.py to avoid a circular import (cli imports parallel).
    """
    from cli import NZBDavAdapter, WebDavAdapter
    from nzbdav import wait_for_terminal_job  # noqa: F401 (re-exported via NZBDavAdapter)

    http = HttpClient(headers={"User-Agent": "find-fel-nzbdav/0.1"})
    nzbdav_client = NZBDavClient(http, endpoint.url, endpoint.api_key)
    nzbdav = NZBDavAdapter(
        http,
        nzbdav_client,
        poll_interval=poll_interval,
        timeout=timeout,
    )
    webdav_http = WebDavClient(headers={"User-Agent": "find-fel-nzbdav/0.1"})
    webdav = WebDavAdapter(webdav_http, endpoint)
    return nzbdav, webdav
