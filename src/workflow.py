from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from hydra import HydraSearchResult
from httpclient import redact_url
from models import (
    VERDICT_FEL,
    VERDICT_NOT_FEL,
    Candidate,
    CandidateResult,
    TitleResult,
)


class HydraSearch(Protocol):
    def search(self, title: str) -> HydraSearchResult | list[Candidate]: ...


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
    max_candidates: int | None = None,
) -> TitleResult:
    search_result = _coerce_hydra_search_result(hydra.search(title))
    candidates = _limit_candidates(
        dedupe_candidates(search_result.candidates),
        max_candidates,
    )
    if not candidates:
        if search_result.raw_count == 0:
            return TitleResult.unknown(title, "no_hydra_results")
        if search_result.has_4k_video:
            return TitleResult.not_fel(title, "no_dv_4k_candidates")
        return TitleResult.not_fel(title, "no_4k_video_candidates")

    results: list[CandidateResult] = []
    for candidate in candidates:
        try:
            if nzbdav is None:
                raise RuntimeError("NZBDAV client is not configured")
            job = nzbdav.submit_and_wait(candidate)
        except Exception as exc:
            results.append(
                CandidateResult(
                    candidate=candidate,
                    status="error",
                    reason=_submit_failure_reason(exc),
                )
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
        if (
            probe_result.verdict == VERDICT_NOT_FEL
            and probe_result.reason in _DEFINITIVE_NOT_FEL_PROFILE_REASONS
        ):
            return TitleResult(
                title=title,
                verdict=VERDICT_NOT_FEL,
                reason=probe_result.reason,
                candidates=results,
            )
    return TitleResult(
        title=title,
        verdict="unknown",
        reason="dv_4k_profile_undetected",
        candidates=results,
    )


_DEFINITIVE_NOT_FEL_PROFILE_REASONS = {
    "profile_7_mel",
    "profile_7_low_el_bitrate",
    "not_profile_7",
}


def _coerce_hydra_search_result(
    value: HydraSearchResult | list[Candidate],
) -> HydraSearchResult:
    if isinstance(value, HydraSearchResult):
        return value
    return HydraSearchResult(raw_candidates=value, candidates=value)


import time as _time


def check_title_with_retries(
    title: str,
    hydra,
    nzbdav,
    webdav,
    probe,
    *,
    max_candidates: int | None,
    retries: int,
    retry_wait: float,
    sleep=_time.sleep,
    logger=None,
):
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
                if logger is not None:
                    logger(
                        f"{title}: {type(exc).__name__} on attempt {attempt}/{attempts}, "
                        f"retrying in {wait:.0f}s"
                    )
                sleep(wait)
    assert last_exc is not None
    return (
        TitleResult.unknown(title, _failure_reason(last_exc)),
        True,
    )


def _failure_reason(exc: Exception) -> str:
    if type(exc).__name__ == "HydraError":
        code = getattr(exc, "code", "unknown")
        safe_code = re.sub(r"[^A-Za-z0-9]+", "_", str(code)).strip("_") or "unknown"
        return f"error_Hydra_{safe_code}"
    return f"error_{type(exc).__name__}"


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


def _limit_candidates(
    candidates: list[Candidate],
    max_candidates: int | None,
) -> list[Candidate]:
    if max_candidates is None or max_candidates <= 0:
        return candidates
    return candidates[:max_candidates]


def _submit_failure_reason(exc: Exception) -> str:
    text = str(exc).lower()
    if "article" in text and "not found" in text:
        return "article_health_failed"
    return "submit_failed"


def _normalize_release_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
