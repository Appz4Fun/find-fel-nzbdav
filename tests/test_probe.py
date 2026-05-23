from __future__ import annotations

from pathlib import Path

from probe import MediaProbe, classify_probe_text


def test_classifies_profile_7_fel():
    text = "Dolby Vision dvhe.07.06 BL+EL+RPU Profile 7 EL type: FEL full enhancement layer"

    result = classify_probe_text(text)

    assert result.verdict == "fel"
    assert result.reason == "profile_7_fel"


def test_classifies_profile_7_mel_as_not_fel():
    text = "Dolby Vision dvhe.07.06 BL+EL+RPU Profile 7 EL type: MEL minimal enhancement layer"

    result = classify_probe_text(text)

    assert result.verdict == "not_fel"
    assert result.reason == "profile_7_mel"


def test_classifies_dovi_tool_profile_7_fel_summary():
    result = classify_probe_text("Profile: 7 (FEL)")

    assert result.verdict == "fel"
    assert result.reason == "profile_7_fel"


def test_classifies_dovi_tool_profile_7_mel_summary():
    result = classify_probe_text("Profile: 7 (MEL)")

    assert result.verdict == "not_fel"
    assert result.reason == "profile_7_mel"


def test_classifies_non_profile_7_as_not_fel():
    text = "Dolby Vision dvhe.08.06 BL+RPU Profile 8.1"

    result = classify_probe_text(text)

    assert result.verdict == "not_fel"
    assert result.reason == "not_profile_7"


def test_classifies_profile_7_without_el_type_as_unknown():
    text = "Dolby Vision dvhe.07.06 BL+EL+RPU Profile 7"

    result = classify_probe_text(text)

    assert result.verdict == "unknown"
    assert result.reason == "profile_7_el_type_unknown"


def test_classifies_profile_7_high_el_bitrate_as_fel():
    text = (
        "Dolby Vision Profile 7 el_present_flag: 1\n"
        "enhancement_layer_bitrate_mbps: 2.414"
    )

    result = classify_probe_text(text)

    assert result.verdict == "fel"
    assert result.reason == "profile_7_high_el_bitrate"


def test_classifies_profile_7_low_el_bitrate_as_not_fel():
    text = (
        "Dolby Vision Profile 7 el_present_flag: 1\n"
        "enhancement_layer_bitrate_mbps: 0.250"
    )

    result = classify_probe_text(text)

    assert result.verdict == "not_fel"
    assert result.reason == "profile_7_low_el_bitrate"


def test_does_not_confirm_fel_from_negated_fel_text():
    text = "Dolby Vision Profile 7, this is not FEL"

    result = classify_probe_text(text)

    assert result.verdict == "unknown"
    assert result.reason == "profile_7_el_type_unknown"


def test_media_probe_passes_headers_and_captures_command_output():
    calls = []

    def fake_run(command, *, capture_output, text, timeout, check):
        calls.append(
            {
                "command": command,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
                "check": check,
            }
        )
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"hevc")
        if command[:2] == ["dovi_tool", "demux"]:
            Path(command[-1]).write_bytes(b"x" * 2_000_000)
        if command[:2] == ["dovi_tool", "extract-rpu"]:
            Path(command[-1]).write_bytes(b"rpu")
        stdout = (
            "Dolby Vision Profile 7"
            if command[0] == "ffprobe"
            else ""
        )
        return type("Completed", (), {"returncode": 0, "stdout": stdout, "stderr": "tool stderr"})()

    probe = MediaProbe(runner=fake_run, command_timeout=12, sample_seconds=3)

    result = probe.probe("http://example.test/movie.mkv", {"Authorization": "Basic abc"})

    assert result.verdict == "fel"
    assert result.reason == "profile_7_high_el_bitrate"


def test_media_probe_fast_path_confirms_fel_without_slow_tools():
    calls = []

    def fake_run(command, *, capture_output, text, timeout, check):
        calls.append(command)
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"hevc")
        if command[:2] == ["dovi_tool", "extract-rpu"]:
            Path(command[-1]).write_bytes(b"rpu")
        stdout = "Profile: 7 (FEL)" if command[:2] == ["dovi_tool", "info"] else ""
        return type("Completed", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    result = MediaProbe(runner=fake_run, command_timeout=12).probe("http://example/movie.mkv")

    assert result.verdict == "fel"
    assert result.reason == "profile_7_fel"
    assert [command[0] for command in calls] == ["ffmpeg", "dovi_tool", "dovi_tool"]
    assert all(command[0] not in {"ffprobe", "mediainfo"} for command in calls)
    assert all(command[:2] != ["dovi_tool", "demux"] for command in calls)


def test_media_probe_fast_path_confirms_mel_as_not_fel():
    calls = []

    def fake_run(command, *, capture_output, text, timeout, check):
        calls.append(command)
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"hevc")
        if command[:2] == ["dovi_tool", "extract-rpu"]:
            Path(command[-1]).write_bytes(b"rpu")
        stdout = "Profile: 7 (MEL)" if command[:2] == ["dovi_tool", "info"] else ""
        return type("Completed", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    result = MediaProbe(runner=fake_run, command_timeout=12).probe("http://example/movie.mkv")

    assert result.verdict == "not_fel"
    assert result.reason == "profile_7_mel"
    assert [command[0] for command in calls] == ["ffmpeg", "dovi_tool", "dovi_tool"]


def test_media_probe_fast_ffmpeg_uses_low_probe_one_frame_and_headers():
    calls = []

    def fake_run(command, *, capture_output, text, timeout, check):
        calls.append(command)
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"hevc")
        if command[:2] == ["dovi_tool", "extract-rpu"]:
            Path(command[-1]).write_bytes(b"rpu")
        stdout = "Profile: 7 (FEL)" if command[:2] == ["dovi_tool", "info"] else ""
        return type("Completed", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    result = MediaProbe(runner=fake_run, command_timeout=12).probe(
        "http://example/movie.mkv",
        {"Authorization": "Basic abc"},
    )

    ffmpeg = calls[0]
    assert ffmpeg[0] == "ffmpeg"
    assert "-frames:v" in ffmpeg
    assert ffmpeg[ffmpeg.index("-frames:v") + 1] == "1"
    assert "-analyzeduration" in ffmpeg
    assert ffmpeg[ffmpeg.index("-analyzeduration") + 1] == "0"
    assert "-probesize" in ffmpeg
    assert ffmpeg[ffmpeg.index("-probesize") + 1] == "4096"
    assert "-headers" in ffmpeg
    assert ffmpeg[ffmpeg.index("-headers") + 1] == "Authorization: Basic abc\r\n"
    assert "-headers <redacted>" in result.summary


def test_media_probe_fast_path_inconclusive_falls_back_to_slow_probe():
    calls = []

    def fake_run(command, *, capture_output, text, timeout, check):
        calls.append(command)
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"hevc")
        if command[:2] == ["dovi_tool", "extract-rpu"]:
            Path(command[-1]).write_bytes(b"rpu")
        if command[:2] == ["dovi_tool", "demux"]:
            Path(command[-1]).write_bytes(b"x" * 2_000_000)
        stdout = "Dolby Vision Profile 7" if command[0] == "ffprobe" else ""
        return type("Completed", (), {"returncode": 0, "stdout": stdout, "stderr": "tool stderr"})()

    result = MediaProbe(runner=fake_run, command_timeout=12, sample_seconds=3).probe(
        "http://example/movie.mkv"
    )

    assert result.verdict == "fel"
    assert result.reason == "profile_7_high_el_bitrate"
    assert [command[0] for command in calls[:3]] == ["ffmpeg", "dovi_tool", "dovi_tool"]
    assert any(command[0] == "ffprobe" for command in calls)
    assert any(command[0] == "mediainfo" for command in calls)
    assert any(command[:2] == ["dovi_tool", "demux"] for command in calls)
    assert "ffprobe" in result.summary
    assert "tool stderr" in result.summary
    assert "enhancement_layer_bitrate_mbps" in result.summary
