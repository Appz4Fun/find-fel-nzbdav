from pathlib import Path

from config import Config


def test_console_script_target_is_importable():
    from cli import main

    assert callable(main)


def test_loads_required_env_and_defaults_webdav_url(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "NZB_DAV_URL=http://server:3000\n"
        "NZB_DAV_API_KEY=nzbdav-secret\n"
        "HYDRA_URL=http://server:5076/\n"
        "HYDRA_API_KEY=hydra-secret\n",
        encoding="utf-8",
    )

    config = Config.from_env_file(env_path)

    assert config.nzbdav_url == "http://server:3000"
    assert config.webdav_url == "http://server:3000"
    assert config.hydra_url == "http://server:5076"
    assert config.max_candidates == 3
