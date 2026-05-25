from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "sample_pool_mkvs.py"
    spec = importlib.util.spec_from_file_location("sample_pool_mkvs", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sample_output_path_preserves_server_and_webdav_path():
    module = _load_script_module()

    output = module.sample_output_path(
        Path("data/sources"),
        "nzbdav-3001",
        "/content/Movie%20Job/%5B01%2F10%5D%20Movie.mkv",
    )

    assert output == Path("data/sources/nzbdav-3001/content/Movie Job/[01_10] Movie.mkv")


def test_build_ffmpeg_command_creates_one_second_mkv_sample_with_headers():
    module = _load_script_module()

    command = module.build_ffmpeg_command(
        "http://localhost:3001/content/Movie.mkv",
        {"Authorization": "Basic token"},
        Path("data/sources/nzbdav-3001/content/Movie.mkv"),
    )

    assert command[:4] == ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    assert "-headers" in command
    assert command[command.index("-headers") + 1] == "Authorization: Basic token\r\n"
    assert "-t" in command
    assert command[command.index("-t") + 1] == "1"
    assert command[-1] == "data/sources/nzbdav-3001/content/Movie.mkv"


def test_mkv_filter_handles_percent_encoded_names():
    module = _load_script_module()
    files = [
        module.WebDavFile("/content/job/Movie%20Name.mkv", "Movie Name.mkv", 10),
        module.WebDavFile("/content/job/poster.jpg", "poster.jpg", 20),
    ]

    assert module.filter_mkvs(files) == [files[0]]
