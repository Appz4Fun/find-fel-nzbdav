from __future__ import annotations

import argparse
from dataclasses import replace
import datetime
import json
from pathlib import Path
import sys
import time
from typing import Sequence

from bluray_com import BlurayComSource
from catalog import render_catalog_payload
from config import Config
import db
import parallel
from httpclient import HttpClient, redact_url
from hydra import HydraSearchResult, search_hydra
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
from workflow import StreamCandidate, check_title, check_title_with_retries


_DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
_PROFILE_UNDETECTED_REASON = "dv_4k_profile_undetected"
_PROFILE_UNDETECTED_LOG_MESSAGE = (
    "DV 4k was found but unable to detect profile skipping to next title"
)
_PERSIST_NOT_FEL_REASONS = {
    "no_4k_video_candidates",
    "no_dv_4k_candidates",
    "profile_7_mel",
    "profile_7_low_el_bitrate",
    "not_profile_7",
}


class HydraAdapter:
    def __init__(self, http: HttpClient, config: Config) -> None:
        self.http = http
        self.config = config

    def search(self, title: str) -> HydraSearchResult:
        return search_hydra(
            self.http,
            self.config.hydra_url,
            self.config.hydra_api_key,
            title,
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
    def __init__(self, http: WebDavClient, endpoint) -> None:
        self.http = http
        self.endpoint = endpoint

    def find_mkv(self, storage: str) -> StreamCandidate | None:
        path = storage_to_webdav_path(storage)
        mkv = find_largest_mkv(
            self.http,
            self.endpoint.webdav_url,
            path,
            username=self.endpoint.webdav_user,
            password=self.endpoint.webdav_pass,
        )
        if mkv is None:
            return None
        headers = (
            basic_auth_header(self.endpoint.webdav_user, self.endpoint.webdav_pass)
            if self.endpoint.webdav_user and self.endpoint.webdav_pass
            else {}
        )
        return StreamCandidate(
            path=mkv.path,
            url=join_webdav_url(self.endpoint.webdav_url, mkv.path),
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
    parser.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=_DEFAULT_MAX_CONSECUTIVE_FAILURES,
    )
    parser.add_argument("--db", default="data/find-fel.db")
    parser.add_argument("--no-db", action="store_true", dest="no_db")
    parser.add_argument("--pool", default="pool.yaml")
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
    parallel_run=None,
) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv and effective_argv[0] == "catalog":
        return main_catalog(effective_argv[1:], catalog_source=catalog_source)

    args = build_parser().parse_args(effective_argv)
    if args.title is not None and args.titles_file is not None:
        print(
            "error: pass at most one of TITLE or --titles-file PATH",
            file=sys.stderr,
        )
        return 2

    default_mode = args.title is None and args.titles_file is None
    if default_mode:
        db_path_obj = Path(args.db)
        if args.no_db or not db_path_obj.exists():
            if args.no_db:
                print(
                    "error: default mode requires a database; "
                    "do not combine with --no-db",
                    file=sys.stderr,
                )
            else:
                print(
                    f"error: no database at {db_path_obj}; nothing to scan",
                    file=sys.stderr,
                )
            return 2

    pool_path = Path(args.pool) if args.pool else None
    config = Config.from_env_file(args.env, pool_path=pool_path)
    if args.max_candidates is not None:
        config = _replace_config(config, max_candidates=args.max_candidates)
    if args.timeout is not None:
        config = _replace_config(config, timeout=args.timeout)
    if args.poll_interval is not None:
        config = _replace_config(config, poll_interval=args.poll_interval)

    if args.title is not None:
        titles: list[str] = [args.title]
    elif args.titles_file is not None:
        titles = parse_titles_file(args.titles_file)
    else:
        titles = []  # filled from db.pending_titles below

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
        config.endpoints[0],
    )
    probe = probe or MediaProbe(command_timeout=30, sample_seconds=args.probe_seconds)

    log_path = Path(args.log_file) if args.log_file else default_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"logging to {log_path}", file=sys.stderr)

    use_db = not args.no_db
    db_conn = db.connect(Path(args.db)) if use_db else None

    if default_mode and db_conn is not None:
        titles = list(db.pending_titles(db_conn))

    if len(config.endpoints) > 1:
        state = {"has_definitive_verdict": False}

        def _on_result(title: str, result, failed: bool) -> None:
            if args.json_output:
                print(render_json(result), flush=True)
            else:
                print(render_text(result), flush=True)
            try:
                log_file_handle.write(format_log_line(result) + "\n")
                skip_message = skip_log_message(result)
                if skip_message:
                    log_file_handle.write(skip_message + "\n")
                log_file_handle.flush()
            except Exception:
                pass
            if db_conn is not None and should_persist_result(result):
                db.upsert_result(
                    db_conn,
                    title,
                    result.verdict,
                    result.reason or "",
                    datetime.datetime.now(),
                )
            if should_persist_result(result):
                state["has_definitive_verdict"] = True

        runner = parallel_run if parallel_run is not None else parallel.run_parallel
        with log_path.open("a", encoding="utf-8") as log_file_handle:
            summary = runner(
                titles,
                list(config.endpoints),
                hydra=hydra,
                probe=probe,
                max_candidates=config.max_candidates,
                poll_interval=config.poll_interval,
                nzbdav_timeout=config.timeout,
                retries=args.retries,
                retry_wait=args.retry_wait,
                max_consecutive_failures=args.max_consecutive_failures,
                on_result=_on_result,
            )

        if db_conn is not None:
            db_conn.close()
        if summary is not None and getattr(summary, "aborted", False):
            print(
                f"aborting: {args.max_consecutive_failures} consecutive failures "
                f"({getattr(summary, 'unprocessed', 0)} titles unprocessed)",
                file=sys.stderr,
            )
            return 3
        return 0 if state["has_definitive_verdict"] else 2

    # else: fall through to the existing sequential path below

    has_definitive_verdict = False
    consecutive_failures = 0
    aborted = False
    with log_path.open("a", encoding="utf-8") as log_file:
        for index, title in enumerate(titles):
            result, failed = check_title_with_retries(
                title,
                hydra,
                nzbdav,
                webdav,
                probe,
                max_candidates=config.max_candidates,
                retries=args.retries,
                retry_wait=args.retry_wait,
                logger=lambda msg: print(msg, file=sys.stderr, flush=True),
            )

            if args.json_output:
                print(render_json(result), flush=True)
            else:
                if index > 0:
                    print()
                print(render_text(result), flush=True)

            log_file.write(format_log_line(result) + "\n")
            skip_message = skip_log_message(result)
            if skip_message:
                log_file.write(skip_message + "\n")
            log_file.flush()
            if db_conn is not None and should_persist_result(result):
                db.upsert_result(
                    db_conn,
                    title,
                    result.verdict,
                    result.reason or "",
                    datetime.datetime.now(),
                )

            if should_persist_result(result):
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

    if db_conn is not None:
        db_conn.close()

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


def should_persist_result(result: TitleResult) -> bool:
    if result.verdict == VERDICT_FEL:
        return True
    return (
        result.verdict == VERDICT_NOT_FEL
        and (result.reason or "") in _PERSIST_NOT_FEL_REASONS
    )


def skip_log_message(result: TitleResult) -> str | None:
    if result.reason == _PROFILE_UNDETECTED_REASON:
        return _PROFILE_UNDETECTED_LOG_MESSAGE
    return None


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
    return replace(config, **changes)


def _safe_job_name(title: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in title)
    return " ".join(cleaned.split())[:180] or "find-fel-nzbdav"


if __name__ == "__main__":
    raise SystemExit(main())
