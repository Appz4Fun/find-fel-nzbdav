from __future__ import annotations

import argparse
from dataclasses import asdict
import datetime
import json
from pathlib import Path
import sys
import time
from typing import Sequence

from bluray_com import BlurayComSource
from catalog import render_catalog_payload
from config import Config
from httpclient import HttpClient, redact_url
from hydra import search_hydra
from models import (
    VERDICT_FEL,
    VERDICT_NOT_FEL,
    Candidate,
    CandidateResult,
    TitleResult,
)
from nzbdav import NZBDavClient, wait_for_terminal_job, storage_to_webdav_path
from probe import MediaProbe
from webdav import (
    WebDavClient,
    basic_auth_header,
    find_largest_mkv,
    join_webdav_url,
)
from workflow import StreamCandidate, check_title


class HydraAdapter:
    def __init__(self, http: HttpClient, config: Config) -> None:
        self.http = http
        self.config = config

    def search(self, title: str) -> list[Candidate]:
        return search_hydra(
            self.http,
            self.config.hydra_url,
            self.config.hydra_api_key,
            title,
            limit=100,
            timeout=30,
        )


class NZBDavAdapter:
    def __init__(
        self,
        http: HttpClient,
        client: NZBDavClient,
        *,
        poll_interval: float,
        timeout: float,
    ) -> None:
        self.http = http
        self.client = client
        self.poll_interval = poll_interval
        self.timeout = timeout

    def submit_and_wait(self, candidate: Candidate):
        job_name = _safe_job_name(candidate.release_title)
        nzb_data = self.http.get_bytes(candidate.link, timeout=60)
        nzo_id = self.client.submit_bytes(nzb_data, job_name, timeout=self.timeout)
        return wait_for_terminal_job(
            self.client,
            nzo_id,
            poll_interval=self.poll_interval,
            timeout=self.timeout,
        )


class WebDavAdapter:
    def __init__(self, http: WebDavClient, config: Config) -> None:
        self.http = http
        self.config = config

    def find_mkv(self, storage: str) -> StreamCandidate | None:
        path = storage_to_webdav_path(storage)
        mkv = find_largest_mkv(
            self.http,
            self.config.webdav_url,
            path,
            username=self.config.webdav_user,
            password=self.config.webdav_pass,
        )
        if mkv is None:
            return None
        headers = (
            basic_auth_header(self.config.webdav_user, self.config.webdav_pass)
            if self.config.webdav_user and self.config.webdav_pass
            else {}
        )
        return StreamCandidate(
            path=mkv.path,
            url=join_webdav_url(self.config.webdav_url, mkv.path),
            headers=headers,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="find-fel-nzbdav",
        description="Check Hydra/NZBDAV Dolby Vision 4K MKV candidates for Profile 7 FEL.",
    )
    parser.add_argument("title", nargs="?")
    parser.add_argument("--titles-file")
    parser.add_argument("--log-file")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--max-candidates", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--poll-interval", type=float, default=None)
    parser.add_argument("--probe-seconds", type=int, default=10)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-wait", type=float, default=10.0)
    parser.add_argument("--max-consecutive-failures", type=int, default=3)
    return parser


def build_catalog_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="find-fel-nzbdav catalog",
        description="Build a Dolby Vision 4K catalog from supported sources.",
    )
    parser.add_argument("--source", choices=["bluray-com"], default="bluray-com")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--country", default="all")
    parser.add_argument("--cache-dir", default=".cache/bluray-com")
    parser.add_argument("--delay-seconds", type=float, default=10.0)
    parser.add_argument("--include-releases", action="store_true")
    parser.add_argument("--output", default=None)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    hydra=None,
    nzbdav=None,
    webdav=None,
    probe=None,
    catalog_source=None,
) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv and effective_argv[0] == "catalog":
        return main_catalog(effective_argv[1:], catalog_source=catalog_source)

    args = build_parser().parse_args(effective_argv)
    if (args.title is None) == (args.titles_file is None):
        print(
            "error: provide exactly one of TITLE or --titles-file PATH",
            file=sys.stderr,
        )
        return 2
    config = Config.from_env_file(args.env)
    if args.max_candidates is not None:
        config = _replace_config(config, max_candidates=args.max_candidates)
    if args.timeout is not None:
        config = _replace_config(config, timeout=args.timeout)
    if args.poll_interval is not None:
        config = _replace_config(config, poll_interval=args.poll_interval)

    titles = (
        [args.title]
        if args.title is not None
        else parse_titles_file(args.titles_file)
    )

    http = HttpClient(headers={"User-Agent": "find-fel-nzbdav/0.1"})
    hydra = hydra or HydraAdapter(http, config)
    nzbdav = nzbdav or NZBDavAdapter(
        http,
        NZBDavClient(http, config.nzbdav_url, config.nzbdav_api_key),
        poll_interval=config.poll_interval,
        timeout=config.timeout,
    )
    webdav = webdav or WebDavAdapter(
        WebDavClient(headers={"User-Agent": "find-fel-nzbdav/0.1"}),
        config,
    )
    probe = probe or MediaProbe(command_timeout=30, sample_seconds=args.probe_seconds)

    log_path = Path(args.log_file) if args.log_file else default_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"logging to {log_path}", file=sys.stderr)

    has_definitive_verdict = False
    consecutive_failures = 0
    aborted = False
    with log_path.open("a", encoding="utf-8") as log_file:
        for index, title in enumerate(titles):
            result, failed = _check_with_retries(
                title,
                hydra,
                nzbdav,
                webdav,
                probe,
                max_candidates=config.max_candidates,
                retries=args.retries,
                retry_wait=args.retry_wait,
            )

            if args.json_output:
                print(render_json(result), flush=True)
            else:
                if index > 0:
                    print()
                print(render_text(result), flush=True)

            log_file.write(format_log_line(result) + "\n")
            log_file.flush()

            if result.verdict in {VERDICT_FEL, VERDICT_NOT_FEL}:
                has_definitive_verdict = True

            if failed:
                consecutive_failures += 1
                if consecutive_failures >= args.max_consecutive_failures:
                    remaining = len(titles) - index - 1
                    print(
                        f"aborting: {consecutive_failures} consecutive failures "
                        f"({remaining} titles unprocessed)",
                        file=sys.stderr,
                    )
                    aborted = True
                    break
            else:
                consecutive_failures = 0

    if aborted:
        return 3
    return 0 if has_definitive_verdict else 2


def main_catalog(argv: Sequence[str] | None = None, *, catalog_source=None) -> int:
    args = build_catalog_parser().parse_args(argv)
    if catalog_source is None:
        catalog_source = BlurayComSource(
            HttpClient(headers={"User-Agent": "find-fel-nzbdav/0.1"}),
            cache_dir=args.cache_dir,
            country=args.country,
            delay_seconds=args.delay_seconds,
        )

    releases = catalog_source.discover_releases(pages=args.pages)
    payload = render_catalog_payload(
        releases,
        include_releases=args.include_releases,
        source=args.source,
    )
    output = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(output, encoding="utf-8")
        print(f"Wrote {output_path}")
    else:
        print(output)
    return 0


def _check_with_retries(
    title: str,
    hydra,
    nzbdav,
    webdav,
    probe,
    *,
    max_candidates: int,
    retries: int,
    retry_wait: float,
) -> tuple[TitleResult, bool]:
    attempts = max(1, retries + 1)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = check_title(
                title,
                hydra,
                nzbdav,
                webdav,
                probe,
                max_candidates=max_candidates,
            )
            return result, False
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                wait = retry_wait * attempt
                print(
                    f"{title}: {type(exc).__name__} on attempt {attempt}/{attempts}, "
                    f"retrying in {wait:.0f}s",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(wait)
    assert last_exc is not None
    return (
        TitleResult.unknown(title, f"error_{type(last_exc).__name__}"),
        True,
    )


def render_json(result: TitleResult) -> str:
    return json.dumps(_title_result_payload(result), sort_keys=True)


def render_text(result: TitleResult) -> str:
    lines = [f"{result.title}: {result.verdict} ({result.reason})"]
    for item in result.candidates:
        lines.append(
            f"- {item.status}: {item.candidate.release_title}"
            + (f" [{item.reason}]" if item.reason else "")
        )
    return "\n".join(lines)


def parse_titles_file(path: str | Path) -> list[str]:
    titles: list[str] = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        titles.append(line)
    return titles


def default_log_path(now: datetime.datetime | None = None) -> Path:
    now = now or datetime.datetime.now()
    return Path("logs") / f"find-fel-{now.strftime('%Y%m%d-%H%M%S')}.log"


def format_log_line(result: TitleResult, now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now()
    timestamp = now.isoformat(timespec="seconds")
    return f"[{timestamp}] {result.title}: {result.verdict} ({result.reason})"


def _title_result_payload(result: TitleResult) -> dict:
    return {
        "title": result.title,
        "verdict": result.verdict,
        "reason": result.reason,
        "candidates": [_candidate_result_payload(item) for item in result.candidates],
    }


def _candidate_result_payload(result: CandidateResult) -> dict:
    return {
        "release_title": result.candidate.release_title,
        "link": redact_url(result.candidate.link),
        "size_bytes": result.candidate.size_bytes,
        "indexer": result.candidate.indexer,
        "pubdate": result.candidate.pubdate,
        "status": result.status,
        "reason": result.reason,
        "nzo_id": result.nzo_id,
        "webdav_path": result.webdav_path,
        "stream_url_redacted": result.stream_url_redacted,
        "probe_summary": result.probe_summary,
    }


def _replace_config(config: Config, **changes) -> Config:
    values = asdict(config)
    values.update(changes)
    return Config(**values)


def _safe_job_name(title: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in title)
    return " ".join(cleaned.split())[:180] or "find-fel-nzbdav"


if __name__ == "__main__":
    raise SystemExit(main())
