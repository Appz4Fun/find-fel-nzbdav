from __future__ import annotations

from dataclasses import dataclass, field


VERDICT_FEL = "fel"
VERDICT_NOT_FEL = "not_fel"
VERDICT_UNKNOWN = "unknown"


@dataclass(order=True, frozen=True)
class Candidate:
    sort_index: int = field(init=False, repr=False)
    release_title: str
    link: str
    size_bytes: int
    indexer: str | None = None
    pubdate: str | None = None
    attributes: dict[str, str] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort_index", self.size_bytes)


@dataclass(frozen=True)
class CandidateResult:
    candidate: Candidate
    status: str
    reason: str | None = None
    nzo_id: str | None = None
    webdav_path: str | None = None
    stream_url_redacted: str | None = None
    probe_summary: str | None = None


@dataclass(frozen=True)
class TitleResult:
    title: str
    verdict: str
    reason: str | None = None
    candidates: list[CandidateResult] = field(default_factory=list)

    @classmethod
    def not_fel(cls, title: str, reason: str) -> "TitleResult":
        return cls(title=title, verdict=VERDICT_NOT_FEL, reason=reason)

    @classmethod
    def unknown(cls, title: str, reason: str) -> "TitleResult":
        return cls(title=title, verdict=VERDICT_UNKNOWN, reason=reason)

    @classmethod
    def fel(
        cls,
        title: str,
        reason: str = "confirmed_fel",
        candidates: list[CandidateResult] | None = None,
    ) -> "TitleResult":
        return cls(
            title=title,
            verdict=VERDICT_FEL,
            reason=reason,
            candidates=candidates or [],
        )
