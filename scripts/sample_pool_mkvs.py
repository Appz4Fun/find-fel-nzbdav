#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from webdav import (  # noqa: E402
    WebDavClient,
    WebDavFile,
    _parse_propfind_files,
    basic_auth_header,
    join_webdav_url,
)


@dataclass(frozen=True)
class PoolEndpoint:
    label: str
    webdav_url: str
    webdav_user: str | None
    webdav_pass: str | None


@dataclass
class ServerStats:
    discovered: int = 0
    created: int = 0
    skipped: int = 0
    failed: int = 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    endpoints = load_pool(Path(args.pool))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    total = ServerStats()
    for endpoint in endpoints:
        stats = sample_endpoint(
            endpoint,
            output_dir,
            overwrite=args.overwrite,
            timeout=args.timeout,
            ffmpeg_timeout=args.ffmpeg_timeout,
            dry_run=args.dry_run,
        )
        total.discovered += stats.discovered
        total.created += stats.created
        total.skipped += stats.skipped
        total.failed += stats.failed
        print(
            f"{endpoint.label}: discovered={stats.discovered} "
            f"created={stats.created} skipped={stats.skipped} failed={stats.failed}",
            flush=True,
        )

    print(
        f"total: discovered={total.discovered} created={total.created} "
        f"skipped={total.skipped} failed={total.failed}",
        flush=True,
    )
    return 1 if total.failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create one-second MKV samples for every MKV exposed by a pool of NZBDAV WebDAV servers."
    )
    parser.add_argument("--pool", default="pool.yaml")
    parser.add_argument("--output-dir", default="data/sources")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--ffmpeg-timeout", type=float, default=120.0)
    return parser


def load_pool(path: Path) -> list[PoolEndpoint]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a YAML list")

    endpoints: list[PoolEndpoint] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"pool entry {index} must be a mapping")
        webdav_url = str(entry.get("webdav_url") or entry.get("url") or "").strip()
        if not webdav_url:
            raise ValueError(f"pool entry {index} missing url/webdav_url")
        endpoints.append(
            PoolEndpoint(
                label=server_label(webdav_url, index),
                webdav_url=webdav_url.rstrip("/"),
                webdav_user=entry.get("webdav_user") or None,
                webdav_pass=entry.get("webdav_pass") or None,
            )
        )
    return endpoints


def server_label(webdav_url: str, index: int) -> str:
    parsed = urlsplit(webdav_url)
    if parsed.port is not None:
        return f"nzbdav-{parsed.port}"
    host = parsed.hostname or f"entry-{index}"
    return _safe_path_segment(f"nzbdav-{host}")


def sample_endpoint(
    endpoint: PoolEndpoint,
    output_dir: Path,
    *,
    overwrite: bool,
    timeout: float,
    ffmpeg_timeout: float,
    dry_run: bool,
) -> ServerStats:
    stats = ServerStats()
    headers = (
        basic_auth_header(endpoint.webdav_user, endpoint.webdav_pass)
        if endpoint.webdav_user and endpoint.webdav_pass
        else {}
    )
    try:
        files = list_mkvs(endpoint, headers, timeout=timeout)
    except Exception as exc:
        print(f"{endpoint.label}: propfind failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        stats.failed += 1
        return stats

    stats.discovered = len(files)
    for file in files:
        output_path = sample_output_path(output_dir, endpoint.label, file.path)
        if output_path.exists() and not overwrite:
            stats.skipped += 1
            continue

        stream_url = join_webdav_url(endpoint.webdav_url, file.path)
        command = build_ffmpeg_command(stream_url, headers, output_path)
        if dry_run:
            print(f"dry-run: {output_path}")
            stats.skipped += 1
            continue

        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=ffmpeg_timeout,
            check=False,
        )
        if result.returncode == 0:
            stats.created += 1
            print(f"created: {output_path}")
        else:
            stats.failed += 1
            output_path.unlink(missing_ok=True)
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            message = detail[-1] if detail else f"ffmpeg exited {result.returncode}"
            print(f"failed: {output_path}: {message}", file=sys.stderr)
    return stats


def list_mkvs(endpoint: PoolEndpoint, headers: dict[str, str], *, timeout: float) -> list[WebDavFile]:
    client = WebDavClient(headers={"User-Agent": "find-fel-nzbdav/sample-pool-mkvs"})
    xml_text = client.propfind(
        join_webdav_url(endpoint.webdav_url, "/content/"),
        headers=headers,
        timeout=timeout,
    )
    return filter_mkvs(_parse_propfind_files(xml_text))


def filter_mkvs(files: list[WebDavFile]) -> list[WebDavFile]:
    return [file for file in files if unquote(file.path).lower().endswith(".mkv")]


def sample_output_path(output_dir: Path, server: str, webdav_path: str) -> Path:
    raw_path = urlsplit(webdav_path).path or webdav_path
    parts = [part for part in raw_path.strip("/").split("/") if part]
    safe_parts = [_safe_path_segment(unquote(part)) for part in parts]
    return output_dir / server / Path(*safe_parts)


def build_ffmpeg_command(stream_url: str, headers: dict[str, str], output_path: Path) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if headers:
        command.extend(["-headers", _format_ffmpeg_headers(headers)])
    command.extend(
        [
            "-t",
            "1",
            "-i",
            stream_url,
            "-map",
            "0:v:0",
            "-c",
            "copy",
            str(output_path),
        ]
    )
    return command


def _format_ffmpeg_headers(headers: dict[str, str]) -> str:
    return "".join(f"{name}: {value}\r\n" for name, value in headers.items())


def _safe_path_segment(value: str) -> str:
    cleaned = value.replace("/", "_").replace("\x00", "_")
    cleaned = cleaned.replace(":", "_")
    cleaned = cleaned.strip()
    return cleaned or "_"


if __name__ == "__main__":
    raise SystemExit(main())
