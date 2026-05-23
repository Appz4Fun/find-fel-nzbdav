from __future__ import annotations

from pathlib import Path

from find_fel_nzbdav.probe import MediaProbe, classify_probe_text


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
        if command[:2] == ["dovi_tool", "extract-rpu"]:
            Path(command[-1]).write_bytes(b"rpu")
        stdout = (
            "Dolby Vision Profile 7 EL type: FEL"
            if command[:2] == ["dovi_tool", "info"]
            else ""
        )
        return type("Completed", (), {"returncode": 0, "stdout": stdout, "stderr": "tool stderr"})()

    probe = MediaProbe(runner=fake_run, command_timeout=12, sample_seconds=3)

    result = probe.probe("http://example.test/movie.mkv", {"Authorization": "Basic abc"})

    assert result.verdict == "fel"
    assert result.reason == "profile_7_fel"
    assert calls[0]["command"][0] == "ffprobe"
    assert "-headers" in calls[0]["command"]
    assert calls[0]["command"][calls[0]["command"].index("-headers") + 1] == (
        "Authorization: Basic abc\r\n"
    )
    assert calls[2]["command"][0] == "ffmpeg"
    assert "-headers" in calls[2]["command"]
    assert all(call["timeout"] == 12 for call in calls)
    assert "ffprobe" in result.summary
    assert "tool stderr" in result.summary
    assert "Dolby Vision Profile 7 EL type: FEL" in result.summary
