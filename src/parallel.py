from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterable
from typing import Any

from config import NZBDavEndpoint
from httpclient import HttpClient
from models import TitleResult
from nzbdav import NZBDavClient
from webdav import WebDavClient
from workflow import check_title_with_retries


# Sentinel object placed on the work queue to signal worker shutdown.
_SHUTDOWN = object()


def run_parallel(
    titles: Iterable[str],
    endpoints: list[NZBDavEndpoint],
    *,
    hydra,
    probe,
    max_candidates: int,
    poll_interval: float,
    nzbdav_timeout: float,
    retries: int,
    retry_wait: float,
    on_result: Callable[[str, TitleResult, bool], None],
) -> None:
    if not endpoints:
        raise ValueError("run_parallel requires at least one endpoint")

    titles_list = list(titles)
    if not titles_list:
        return

    work_q: queue.Queue = queue.Queue()
    result_q: queue.Queue = queue.Queue()

    for title in titles_list:
        work_q.put(title)
    for _ in endpoints:
        work_q.put(_SHUTDOWN)

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
            ),
            daemon=False,
            name=f"find-fel-worker-{index}",
        )
        for index, endpoint in enumerate(endpoints)
    ]
    for thread in threads:
        thread.start()

    for _ in range(len(titles_list)):
        title, result, failed = result_q.get()
        on_result(title, result, failed)

    for thread in threads:
        thread.join()


def _worker_loop(
    endpoint: NZBDavEndpoint,
    work_q: queue.Queue,
    result_q: queue.Queue,
    hydra,
    probe,
    max_candidates: int,
    poll_interval: float,
    nzbdav_timeout: float,
    retries: int,
    retry_wait: float,
) -> None:
    nzbdav, webdav = _build_adapters(endpoint, poll_interval, nzbdav_timeout)

    while True:
        item = work_q.get()
        if item is _SHUTDOWN:
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
