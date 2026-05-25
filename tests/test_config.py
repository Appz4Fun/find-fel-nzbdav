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
    assert config.max_candidates is None


def test_config_parses_optional_candidate_cap(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "NZB_DAV_URL=http://server:3000\n"
        "NZB_DAV_API_KEY=nzbdav-secret\n"
        "HYDRA_URL=http://server:5076/\n"
        "HYDRA_API_KEY=hydra-secret\n"
        "FEL_MAX_CANDIDATES=5\n",
        encoding="utf-8",
    )

    config = Config.from_env_file(env_path)

    assert config.max_candidates == 5


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


def test_config_parses_pool_yaml_when_path_exists(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "NZB_DAV_URL=http://ignored:3000\n"
        "NZB_DAV_API_KEY=ignored\n"
        "HYDRA_URL=http://server:5076\n"
        "HYDRA_API_KEY=hydra-secret\n",
        encoding="utf-8",
    )
    pool_path = tmp_path / "pool.yaml"
    pool_path.write_text(
        "- url: http://dav1:3000\n"
        "  api_key: AAA\n"
        "- url: http://dav2:3000\n"
        "  api_key: BBB\n"
        "  webdav_url: http://wd2:3000\n"
        "  webdav_user: u2\n"
        "  webdav_pass: p2\n",
        encoding="utf-8",
    )

    config = Config.from_env_file(env_path, pool_path=pool_path)

    assert len(config.endpoints) == 2
    assert config.endpoints[0] == NZBDavEndpoint(
        url="http://dav1:3000",
        api_key="AAA",
        webdav_url="http://dav1:3000",
        webdav_user=None,
        webdav_pass=None,
    )
    assert config.endpoints[1] == NZBDavEndpoint(
        url="http://dav2:3000",
        api_key="BBB",
        webdav_url="http://wd2:3000",
        webdav_user="u2",
        webdav_pass="p2",
    )


def test_config_falls_back_to_env_when_pool_path_missing(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "NZB_DAV_URL=http://server:3000\n"
        "NZB_DAV_API_KEY=nzbdav-secret\n"
        "HYDRA_URL=http://server:5076\n"
        "HYDRA_API_KEY=hydra-secret\n",
        encoding="utf-8",
    )
    missing_pool = tmp_path / "does-not-exist.yaml"

    config = Config.from_env_file(env_path, pool_path=missing_pool)

    assert len(config.endpoints) == 1
    assert config.endpoints[0].url == "http://server:3000"


def test_config_pool_entry_missing_required_fields_raises(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "NZB_DAV_URL=http://x\n"
        "NZB_DAV_API_KEY=x\n"
        "HYDRA_URL=http://y\n"
        "HYDRA_API_KEY=y\n",
        encoding="utf-8",
    )
    pool_path = tmp_path / "pool.yaml"
    pool_path.write_text(
        "- url: http://dav1:3000\n"
        "  api_key: AAA\n"
        "- url: http://dav2:3000\n",  # missing api_key
        encoding="utf-8",
    )

    import pytest
    with pytest.raises(ValueError, match="pool entry 2 missing 'api_key'"):
        Config.from_env_file(env_path, pool_path=pool_path)


def test_config_pool_entry_ignores_unknown_keys(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "NZB_DAV_URL=http://x\n"
        "NZB_DAV_API_KEY=x\n"
        "HYDRA_URL=http://y\n"
        "HYDRA_API_KEY=y\n",
        encoding="utf-8",
    )
    pool_path = tmp_path / "pool.yaml"
    pool_path.write_text(
        "- url: http://dav1:3000\n"
        "  api_key: AAA\n"
        "  unknown_field: whatever\n",
        encoding="utf-8",
    )

    config = Config.from_env_file(env_path, pool_path=pool_path)

    assert len(config.endpoints) == 1
    assert config.endpoints[0].url == "http://dav1:3000"
