from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import tempfile

from models import VERDICT_FEL, VERDICT_NOT_FEL, VERDICT_UNKNOWN


PROFILE_7_RE = re.compile(r"\bprofile\s*[:=]?\s*7\b|\bdvh[ei]\.07\b", re.IGNORECASE)
NON_PROFILE_7_RE = re.compile(
    r"\bprofile\s*[:=]?\s*(?:5|8|8\.1|9)\b|\bdvh[ei]\.0(?:5|8|9)\b",
    re.IGNORECASE,
)
FEL_RE = re.compile(
    r"\bel\s*type\s*[:=]\s*fel\b|\bfull\s+enhancement\s+layer\b|"
    r"\bprofile\s*[:=]?\s*7\s*\(\s*fel\s*\)",
    re.IGNORECASE,
)
MEL_RE = re.compile(
    r"\bel\s*type\s*[:=]\s*mel\b|\bminimal\s+enhancement\s+layer\b|"
    r"\bprofile\s*[:=]?\s*7\s*\(\s*mel\s*\)",
    re.IGNORECASE,
)
EL_BITRATE_RE = re.compile(
    r"\benhancement_layer_bitrate_mbps\s*:\s*([0-9]+(?:\.[0-9]+)?)\b",
    re.IGNORECASE,
)
FEL_MIN_EL_BITRATE_MBPS = 1.0


@dataclass(frozen=True)
class ProbeResult:
    verdict: str
    reason: str
    summary: str


@dataclass(frozen=True)
class _CommandResult:
    command: Sequence[str]
    returncode: int | None
    stdout: str
    stderr: str
    timeout: float
    timed_out: bool = False
    error: str | None = None

    def summary(self) -> str:
        lines = [
            f"$ {_format_command_for_summary(self.command)}",
            f"timeout: {self.timeout}",
        ]
        if self.timed_out:
            lines.append("timed out: true")
        if self.returncode is not None:
            lines.append(f"returncode: {self.returncode}")
        if self.error:
            lines.append(f"error: {self.error}")
        if self.stdout:
            lines.extend(["stdout:", self.stdout.rstrip()])
        if self.stderr:
            lines.extend(["stderr:", self.stderr.rstrip()])
        return "\n".join(lines)


Runner = Callable[..., subprocess.CompletedProcess[str]]


def classify_probe_text(text: str) -> ProbeResult:
    summary = text.strip()

    if PROFILE_7_RE.search(text):
        has_fel = FEL_RE.search(text) is not None
        has_mel = MEL_RE.search(text) is not None
        if has_fel and not has_mel:
            return ProbeResult(VERDICT_FEL, "profile_7_fel", summary)
        if has_mel and not has_fel:
            return ProbeResult(VERDICT_NOT_FEL, "profile_7_mel", summary)
        el_bitrate = _enhancement_layer_bitrate(text)
        if el_bitrate is not None:
            if el_bitrate >= FEL_MIN_EL_BITRATE_MBPS:
                return ProbeResult(VERDICT_FEL, "profile_7_high_el_bitrate", summary)
            return ProbeResult(VERDICT_NOT_FEL, "profile_7_low_el_bitrate", summary)
        return ProbeResult(VERDICT_UNKNOWN, "profile_7_el_type_unknown", summary)

    if NON_PROFILE_7_RE.search(text):
        return ProbeResult(VERDICT_NOT_FEL, "not_profile_7", summary)

    return ProbeResult(VERDICT_UNKNOWN, "dolby_vision_profile_unknown", summary)


class MediaProbe:
    def __init__(
        self,
        *,
        runner: Runner = subprocess.run,
        command_timeout: float = 30,
        sample_seconds: int = 10,
    ) -> None:
        self.runner = runner
        self.command_timeout = command_timeout
        self.sample_seconds = sample_seconds

    def probe(self, stream_url: str, headers: dict[str, str] | None = None) -> ProbeResult:
        fast_result = self._fast_probe(stream_url, headers)
        if fast_result.verdict in {VERDICT_FEL, VERDICT_NOT_FEL}:
            return fast_result
        slow_result = self._slow_probe(stream_url, headers)
        return ProbeResult(
            slow_result.verdict,
            slow_result.reason,
            f"{fast_result.summary}\n\n{slow_result.summary}".strip(),
        )

    def _fast_probe(
        self,
        stream_url: str,
        headers: dict[str, str] | None = None,
    ) -> ProbeResult:
        with tempfile.TemporaryDirectory(prefix="find-fel-fast-probe-") as temp_dir:
            sample_path = Path(temp_dir) / "sample.hevc"
            rpu_path = Path(temp_dir) / "sample.rpu"
            commands = [
                self._ffmpeg_fast_sample_command(stream_url, sample_path, headers),
                ["dovi_tool", "extract-rpu", "-i", str(sample_path), "-o", str(rpu_path)],
                ["dovi_tool", "info", "--summary", "-i", str(rpu_path)],
            ]
            results = [self._run(command) for command in commands]

        summary = "\n\n".join(result.summary() for result in results)
        return classify_probe_text(summary)

    def _slow_probe(
        self,
        stream_url: str,
        headers: dict[str, str] | None = None,
    ) -> ProbeResult:
        with tempfile.TemporaryDirectory(prefix="find-fel-probe-") as temp_dir:
            sample_path = Path(temp_dir) / "sample.hevc"
            enhancement_path = Path(temp_dir) / "enhancement.hevc"
            rpu_path = Path(temp_dir) / "sample.rpu"
            commands = [
                self._ffprobe_command(stream_url, headers),
                ["mediainfo", "--Output=JSON", stream_url],
                self._ffmpeg_sample_command(stream_url, sample_path, headers),
                [
                    "dovi_tool",
                    "demux",
                    "--el-only",
                    "-i",
                    str(sample_path),
                    "-e",
                    str(enhancement_path),
                ],
                ["dovi_tool", "extract-rpu", "-i", str(sample_path), "-o", str(rpu_path)],
                ["dovi_tool", "info", "--summary", "-i", str(rpu_path)],
            ]
            results = [self._run(command) for command in commands]
            measurement_summary = _enhancement_layer_summary(
                enhancement_path,
                self.sample_seconds,
            )

        summary_parts = [result.summary() for result in results]
        if measurement_summary:
            summary_parts.append(measurement_summary)
        summary = "\n\n".join(summary_parts)
        return classify_probe_text(summary)

    def _ffprobe_command(self, stream_url: str, headers: dict[str, str] | None) -> list[str]:
        command = [
            "ffprobe",
            "-hide_banner",
            "-show_format",
            "-show_streams",
            "-print_format",
            "json",
        ]
        if headers:
            command.extend(["-headers", _format_ffmpeg_headers(headers)])
        command.append(stream_url)
        return command

    def _ffmpeg_sample_command(
        self,
        stream_url: str,
        sample_path: Path,
        headers: dict[str, str] | None,
    ) -> list[str]:
        command = ["ffmpeg", "-y"]
        if headers:
            command.extend(["-headers", _format_ffmpeg_headers(headers)])
        command.extend(
            [
                "-t",
                str(self.sample_seconds),
                "-i",
                stream_url,
                "-map",
                "0:v:0",
                "-c",
                "copy",
                str(sample_path),
            ]
        )
        return command

    def _ffmpeg_fast_sample_command(
        self,
        stream_url: str,
        sample_path: Path,
        headers: dict[str, str] | None,
    ) -> list[str]:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-analyzeduration",
            "0",
            "-probesize",
            "4096",
        ]
        if headers:
            command.extend(["-headers", _format_ffmpeg_headers(headers)])
        command.extend(
            [
                "-i",
                stream_url,
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-c",
                "copy",
                str(sample_path),
            ]
        )
        return command

    def _run(self, command: Sequence[str]) -> _CommandResult:
        try:
            completed = self.runner(
                list(command),
                capture_output=True,
                text=True,
                timeout=self.command_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return _CommandResult(
                command=command,
                returncode=None,
                stdout=_to_text(exc.stdout),
                stderr=_to_text(exc.stderr),
                timeout=self.command_timeout,
                timed_out=True,
                error=f"timed out after {exc.timeout} seconds",
            )
        except OSError as exc:
            return _CommandResult(
                command=command,
                returncode=None,
                stdout="",
                stderr="",
                timeout=self.command_timeout,
                error=str(exc),
            )

        return _CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            timeout=self.command_timeout,
        )


def _format_ffmpeg_headers(headers: dict[str, str]) -> str:
    return "".join(f"{name}: {value}\r\n" for name, value in headers.items())


def _format_command_for_summary(command: Sequence[str]) -> str:
    rendered: list[str] = []
    skip_next = False
    for index, part in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        if part == "-headers" and index + 1 < len(command):
            rendered.extend([part, "<redacted>"])
            skip_next = True
            continue
        rendered.append(part)
    return " ".join(rendered)


def _to_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _enhancement_layer_bitrate(text: str) -> float | None:
    match = EL_BITRATE_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _enhancement_layer_summary(path: Path, sample_seconds: int) -> str:
    if not path.exists():
        return ""
    size_bytes = path.stat().st_size
    seconds = max(sample_seconds, 1)
    bitrate_mbps = (size_bytes * 8) / seconds / 1_000_000
    return "\n".join(
        [
            "enhancement_layer:",
            f"enhancement_layer_bytes: {size_bytes}",
            f"enhancement_layer_bitrate_mbps: {bitrate_mbps:.3f}",
        ]
    )
