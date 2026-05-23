from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from httpclient import redact_url
from models import (
    VERDICT_FEL,
    VERDICT_NOT_FEL,
    Candidate,
    CandidateResult,
    TitleResult,
)


class HydraSearch(Protocol):
    def search(self, title: str) -> list[Candidate]: ...


class NZBDavImport(Protocol):
    def submit_and_wait(self, candidate: Candidate): ...


class WebDavDiscovery(Protocol):
    def find_mkv(self, storage: str): ...


class MediaProbeProtocol(Protocol):
    def probe(self, url: str, headers: dict[str, str]): ...


@dataclass(frozen=True)
class StreamCandidate:
    path: str
    url: str
    headers: dict[str, str]


def check_title(
    title: str,
    hydra: HydraSearch,
    nzbdav: NZBDavImport | None,
    webdav: WebDavDiscovery | None,
    probe: MediaProbeProtocol | None,
    *,
    max_candidates: int = 3,
) -> TitleResult:
    candidates = dedupe_candidates(hydra.search(title))[:max_candidates]
    if not candidates:
        return TitleResult.not_fel(title, "no_dv_4k_candidates")

    results: list[CandidateResult] = []
    for candidate in candidates:
        try:
            if nzbdav is None:
                raise RuntimeError("NZBDAV client is not configured")
            job = nzbdav.submit_and_wait(candidate)
        except Exception:
            results.append(
                CandidateResult(candidate=candidate, status="error", reason="submit_failed")
            )
            continue

        nzo_id = getattr(job, "nzo_id", None)
        storage = getattr(job, "storage", None)
        if not storage:
            results.append(
                CandidateResult(
                    candidate=candidate,
                    status="error",
                    reason="missing_storage",
                    nzo_id=nzo_id,
                )
            )
            continue

        try:
            if webdav is None:
                raise RuntimeError("WebDAV client is not configured")
            stream = webdav.find_mkv(storage)
        except Exception:
            results.append(
                CandidateResult(
                    candidate=candidate,
                    status="error",
                    reason="webdav_failed",
                    nzo_id=nzo_id,
                )
            )
            continue

        if stream is None:
            results.append(
                CandidateResult(
                    candidate=candidate,
                    status=VERDICT_NOT_FEL,
                    reason="no_mkv_stream",
                    nzo_id=nzo_id,
                )
            )
            continue

        stream_url = getattr(stream, "url")
        headers = getattr(stream, "headers", {})
        webdav_path = getattr(stream, "path", None)
        try:
            if probe is None:
                raise RuntimeError("media probe is not configured")
            probe_result = probe.probe(stream_url, headers)
        except Exception:
            results.append(
                CandidateResult(
                    candidate=candidate,
                    status="error",
                    reason="probe_failed",
                    nzo_id=nzo_id,
                    webdav_path=webdav_path,
                    stream_url_redacted=redact_url(stream_url),
                )
            )
            continue

        candidate_result = CandidateResult(
            candidate=candidate,
            status=probe_result.verdict,
            reason=probe_result.reason,
            nzo_id=nzo_id,
            webdav_path=webdav_path,
            stream_url_redacted=redact_url(stream_url),
            probe_summary=probe_result.summary,
        )
        results.append(candidate_result)
        if probe_result.verdict == VERDICT_FEL:
            return TitleResult.fel(title, probe_result.reason, results)

    if results and all(result.status == VERDICT_NOT_FEL for result in results):
        return TitleResult(
            title=title,
            verdict=VERDICT_NOT_FEL,
            reason="no_confirmed_fel",
            candidates=results,
        )
    return TitleResult(
        title=title,
        verdict="unknown",
        reason="no_confirmed_fel",
        candidates=results,
    )


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    seen: set[tuple[str, int]] = set()
    deduped: list[Candidate] = []
    for candidate in candidates:
        key = (_normalize_release_title(candidate.release_title), candidate.size_bytes)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _normalize_release_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
