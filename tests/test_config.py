from pathlib import Path

from config import Config, NZBDavEndpoint


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


def test_config_exposes_endpoints_tuple_from_env(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "NZB_DAV_URL=http://server:3000\n"
        "NZB_DAV_API_KEY=nzbdav-secret\n"
        "HYDRA_URL=http://server:5076\n"
        "HYDRA_API_KEY=hydra-secret\n"
        "WEBDAV_URL=http://wd:3000\n"
        "WEBDAV_USER=user1\n"
        "WEBDAV_PASS=pass1\n",
        encoding="utf-8",
    )

    config = Config.from_env_file(env_path)

    assert isinstance(config.endpoints, tuple)
    assert len(config.endpoints) == 1
    assert config.endpoints[0] == NZBDavEndpoint(
        url="http://server:3000",
        api_key="nzbdav-secret",
        webdav_url="http://wd:3000",
        webdav_user="user1",
        webdav_pass="pass1",
    )


def test_config_singleton_properties_proxy_to_first_endpoint(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "NZB_DAV_URL=http://server:3000\n"
        "NZB_DAV_API_KEY=nzbdav-secret\n"
        "HYDRA_URL=http://server:5076\n"
        "HYDRA_API_KEY=hydra-secret\n",
        encoding="utf-8",
    )

    config = Config.from_env_file(env_path)

    assert config.nzbdav_url == "http://server:3000"
    assert config.nzbdav_api_key == "nzbdav-secret"
    assert config.webdav_url == "http://server:3000"
    assert config.webdav_user is None
    assert config.webdav_pass is None
