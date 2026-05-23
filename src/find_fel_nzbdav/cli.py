from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from typing import Sequence

from find_fel_nzbdav.config import Config
from find_fel_nzbdav.http import HttpClient, redact_url
from find_fel_nzbdav.hydra import search_hydra
from find_fel_nzbdav.models import (
    VERDICT_FEL,
    VERDICT_NOT_FEL,
    Candidate,
    CandidateResult,
    TitleResult,
)
from find_fel_nzbdav.nzbdav import NZBDavClient, wait_for_terminal_job, storage_to_webdav_path
from find_fel_nzbdav.probe import MediaProbe
from find_fel_nzbdav.webdav import (
    WebDavClient,
    basic_auth_header,
    find_largest_mkv,
    join_webdav_url,
)
from find_fel_nzbdav.workflow import StreamCandidate, check_title


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
    parser.add_argument("title")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--max-candidates", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--poll-interval", type=float, default=None)
    parser.add_argument("--probe-seconds", type=int, default=10)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    hydra=None,
    nzbdav=None,
    webdav=None,
    probe=None,
) -> int:
    args = build_parser().parse_args(argv)
    config = Config.from_env_file(args.env)
    if args.max_candidates is not None:
        config = _replace_config(config, max_candidates=args.max_candidates)
    if args.timeout is not None:
        config = _replace_config(config, timeout=args.timeout)
    if args.poll_interval is not None:
        config = _replace_config(config, poll_interval=args.poll_interval)

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

    result = check_title(
        args.title,
        hydra,
        nzbdav,
        webdav,
        probe,
        max_candidates=config.max_candidates,
    )

    if args.json_output:
        print(render_json(result))
    else:
        print(render_text(result))
    return exit_code_for_result(result)


def render_json(result: TitleResult) -> str:
    return json.dumps(_title_result_payload(result), indent=2, sort_keys=True)


def render_text(result: TitleResult) -> str:
    lines = [f"{result.title}: {result.verdict} ({result.reason})"]
    for item in result.candidates:
        lines.append(
            f"- {item.status}: {item.candidate.release_title}"
            + (f" [{item.reason}]" if item.reason else "")
        )
    return "\n".join(lines)


def exit_code_for_result(result: TitleResult) -> int:
    if result.verdict in {VERDICT_FEL, VERDICT_NOT_FEL}:
        return 0
    return 2


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
